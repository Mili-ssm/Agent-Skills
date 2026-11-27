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


@pytest.mark.parametrize(("name", "main", "argv"), PASSES)
def test_codex_is_refused_with_the_message_and_a_non_zero_exit(
    name, main, argv, monkeypatch, capsys
):
    monkeypatch.setenv("MEM_RUNNER", "codex")
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == REFUSED
    assert capsys.readouterr().err.strip() == name + MESSAGE


@pytest.mark.parametrize(("name", "main", "argv"), PASSES)
def test_claude_and_a_malformed_setting_are_not_refused(name, main, argv, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [*argv, "--store", "/nonexistent-store"])
    for value in ("claude", "gemini"):
        monkeypatch.setenv("MEM_RUNNER", value)
        with contextlib.suppress(SystemExit):  # a pass that does not take --store: a usage error
            main()
        assert MESSAGE not in capsys.readouterr().err


def test_refuse_codex_is_none_for_claude(monkeypatch):
    monkeypatch.setenv("MEM_RUNNER", "claude")
    assert codex_pass.refuse_codex("x") is None
