import ast
import os
import re
import subprocess
from pathlib import Path

import headless
import pytest
from headless import Raw, Session

BANNED = ("datetime.UTC", "Self", "Required", "NotRequired", "Unpack", "tomllib", "StrEnum")


def test_command_minimal() -> None:
    session = Session("claude", "hi", "haiku", Path("/s.json"))
    assert headless.command(session) == [
        "claude",
        "-p",
        "hi",
        "--model",
        "haiku",
        "--settings",
        "/s.json",
        "--setting-sources",
        "project",
        "--strict-mcp-config",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
    ]


def test_command_full() -> None:
    session = Session(
        "claude",
        "hi",
        "sonnet",
        Path("/s.json"),
        effort="low",
        plugin_dir=Path("/plug"),
        tools=("Read", "Write"),
        allowed=("Read", "Write(/w/*)"),
        disallowed=("Bash",),
        max_budget=0.25,
        agent="curator",
    )
    assert headless.command(session) == [
        "claude",
        "-p",
        "hi",
        "--model",
        "sonnet",
        "--effort",
        "low",
        "--plugin-dir",
        "/plug",
        "--settings",
        "/s.json",
        "--setting-sources",
        "project",
        "--tools",
        "Read,Write",
        "--strict-mcp-config",
        "--allowedTools",
        "Read",
        "Write(/w/*)",
        "--disallowedTools",
        "Bash",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--max-budget-usd",
        "0.2500",
        "--agent",
        "curator",
    ]


def test_command_empty_tools_still_emits_the_flag() -> None:
    cmd = headless.command(Session("c", "p", "m", Path("s"), tools=()))
    assert "--tools" in cmd and not cmd[cmd.index("--tools") + 1]


def fake(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "fake"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return [str(script)]


def test_run_raw_returns_stdout(tmp_path: Path) -> None:
    raw = headless.run_raw(
        fake(tmp_path, "echo hello"), cwd=tmp_path, env={"PATH": "/usr/bin:/bin"}, timeout=10
    )
    assert raw == Raw("hello\n", False)


@pytest.mark.parametrize("errors", [None, "replace"])
def test_run_raw_timeout_keeps_partial_output(tmp_path: Path, errors: str | None) -> None:
    cmd = fake(tmp_path, "echo partial\nexec sleep 5")
    raw = headless.run_raw(
        cmd, cwd=tmp_path, env={"PATH": "/usr/bin:/bin"}, timeout=0.2, errors=errors
    )
    assert raw.timed_out
    assert raw.stdout == "partial\n"


def test_run_raw_missing_binary_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        headless.run_raw([str(tmp_path / "nope")], cwd=tmp_path, env={}, timeout=5)


@pytest.mark.parametrize(
    ("errors", "expected"),
    [(None, {}), ("replace", {"errors": "replace"})],
)
def test_run_raw_passes_errors_only_when_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, errors: str | None, expected: dict
) -> None:
    seen: dict = {}

    def stub(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "out", "")

    monkeypatch.setattr(headless.subprocess, "run", stub)
    env = {"A": "1"}
    assert headless.run_raw(["x"], cwd=tmp_path, env=env, timeout=3, errors=errors) == Raw(
        "out", False
    )
    assert seen == {
        "check": False,
        "cwd": tmp_path,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": 3,
        **expected,
    }


@pytest.mark.parametrize(
    ("partial", "errors", "expected"),
    [
        (b"ab\xffcd", "replace", "ab�cd"),
        (b"ok", None, "ok"),
        ("text", None, "text"),
        (None, None, ""),
    ],
)
def test_run_raw_timeout_decodes_partial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    partial: bytes | str | None,
    errors: str | None,
    expected: str,
) -> None:
    def stub(cmd: list[str], **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd, 1, output=partial)

    monkeypatch.setattr(headless.subprocess, "run", stub)
    assert headless.run_raw(["x"], cwd=tmp_path, env={}, timeout=1, errors=errors) == Raw(
        expected, True
    )


def test_session_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with_mem, plain = tmp_path / "withmem", tmp_path / "plain"
    for folder in (with_mem, plain):
        folder.mkdir()
    (with_mem / "mem").write_text("#!/bin/sh\n")
    (with_mem / "mem").chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([str(with_mem), "", str(plain)]))
    monkeypatch.setenv("KEEP_ME", "3")
    for name in ("MEM_X", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_OPTION_Y", *headless.SESSION_VARS):
        monkeypatch.setenv(name, "v")
    env = headless.session_env()
    assert env["KEEP_ME"] == "3"
    assert env["PATH"] == str(plain)
    for gone in ("MEM_X", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_OPTION_Y", *headless.SESSION_VARS):
        assert gone not in env


def test_source_is_python_310_safe() -> None:
    source = Path(headless.__file__).read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 10))
    for name in BANNED:
        assert not re.search(rf"\b{re.escape(name)}\b", source), name
    assert "except*" not in source
