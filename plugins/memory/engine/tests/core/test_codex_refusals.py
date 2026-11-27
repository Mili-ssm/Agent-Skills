"""The passes that stay on Claude refuse `codex` before they start anything (ADR 0037)."""

import contextlib
import sys

import pytest
from core import codex_pass
from entry import auto, capture
from research import pipeline as research
from synthesize import cli as synthesize

MESSAGE = (
    ": runs on Claude only (ADR 0037: Codex cannot remove the shell from this step); "
    "set runner=claude or pass --runner claude"
)
REFUSED = 2

PASSES = [
    ("mem-synthesize", lambda: synthesize.main("d"), ["mem-synthesize", "--dry-run"]),
    ("mem-auto (the curator)", auto.main, ["mem-auto", "run"]),
    ("mem-research", research.main, ["mem-research", "a question", "--dry-run"]),
    ("mem-capture", capture.main, ["mem-capture", "sweep"]),
    (
        "mem-capture",
        capture.main,
        ["mem-capture", "run", "--transcript", "t.jsonl", "--out", "o.json"],
    ),
    ("mem-capture", capture.main, ["mem-capture", "auto", "--trigger", "session-end"]),
]


@pytest.fixture(autouse=True)
def runner_env(monkeypatch):
    for name in ("MEM_RUNNER", "MEM_RUNNER_OPTION"):
        monkeypatch.delenv(name, raising=False)


IGNORED = ": the default runner codex is ignored for this pass; it runs on Claude (ADR 0037)"


@pytest.fixture
def no_store(monkeypatch, tmp_path):
    """No store and no state: a pass that runs on Claude ends early."""
    for var in ("MEM_STORE", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.mark.usefixtures("no_store")
@pytest.mark.parametrize(("name", "main", "argv"), PASSES)
@pytest.mark.parametrize("source", ["MEM_RUNNER", "MEM_RUNNER_OPTION"])
def test_a_codex_default_is_ignored_with_one_line_and_the_pass_runs(
    request, name, main, argv, source
):
    monkeypatch = request.getfixturevalue("monkeypatch")
    capsys = request.getfixturevalue("capsys")
    monkeypatch.setenv(source, "codex")
    monkeypatch.setattr(sys, "argv", argv)
    with contextlib.suppress(SystemExit):
        main()
    err = capsys.readouterr().err
    assert MESSAGE not in err
    assert err.count(name + IGNORED) == 1


@pytest.mark.parametrize(("name", "main", "argv"), PASSES)
def test_claude_and_a_malformed_setting_are_not_refused(name, main, argv, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [*argv, "--store", "/nonexistent-store"])
    for value in ("claude", "gemini"):
        monkeypatch.setenv("MEM_RUNNER", value)
        with contextlib.suppress(SystemExit):
            main()
        err = capsys.readouterr().err
        assert MESSAGE not in err
        assert IGNORED not in err


def test_an_explicit_codex_is_refused_with_the_message(monkeypatch, capsys):
    monkeypatch.setenv("MEM_RUNNER", "claude")
    assert codex_pass.refuse_codex("mem-x", "codex") == REFUSED
    assert capsys.readouterr().err.strip() == "mem-x" + MESSAGE


def test_an_explicit_claude_is_not_refused(monkeypatch, capsys):
    monkeypatch.setenv("MEM_RUNNER", "codex")
    assert codex_pass.refuse_codex("mem-x", "claude") is None
    assert not capsys.readouterr().err  # asked for claude: nothing to say about the default


def test_refuse_codex_is_none_for_claude(monkeypatch, capsys):
    monkeypatch.setenv("MEM_RUNNER", "claude")
    assert codex_pass.refuse_codex("x") is None
    assert not capsys.readouterr().err


@pytest.mark.parametrize(("name", "main", "argv"), PASSES)
def test_an_explicit_runner_codex_refuses_with_exit_2(name, main, argv, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [*argv, "--runner", "codex"])
    monkeypatch.setenv("MEM_RUNNER", "claude")
    with contextlib.suppress(SystemExit):
        assert main() == REFUSED
    assert capsys.readouterr().err.count(name + MESSAGE) == 1


@pytest.mark.usefixtures("no_store")
@pytest.mark.parametrize(("name", "main", "argv"), PASSES)
def test_an_explicit_runner_claude_beats_a_codex_default_silently(
    name, main, argv, monkeypatch, capsys
):
    monkeypatch.setenv("MEM_RUNNER", "codex")
    monkeypatch.setattr(sys, "argv", [*argv, "--runner", "claude"])
    with contextlib.suppress(SystemExit):
        main()
    err = capsys.readouterr().err
    assert MESSAGE not in err and IGNORED not in err
