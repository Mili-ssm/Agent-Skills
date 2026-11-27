import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from core import headless, runner


def codex_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for var in ("MEM_RUNNER", "MEM_RUNNER_OPTION", "MEM_CODEX", "CODEX_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", str(tmp_path / "emptybin"))
    return tmp_path


def test_default_is_claude(clean: Path) -> None:
    assert runner.resolve_runner(None) == "claude"


def test_precedence_each_source(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conf = clean / "mem-config" / "agent-memory"
    conf.mkdir(parents=True)
    (conf / "runner").write_text(" codex \nclaude\n", encoding="utf-8")
    monkeypatch.setenv("MEM_RUNNER_OPTION", "claude")
    assert runner.resolve_runner(None) == "codex"  # config file beats the plugin option
    monkeypatch.setenv("MEM_RUNNER", "claude")
    assert runner.resolve_runner(None) == "claude"  # env beats the file
    assert runner.resolve_runner("codex") == "codex"  # flag beats env
    (conf / "runner").unlink()
    monkeypatch.delenv("MEM_RUNNER")
    monkeypatch.setenv("MEM_RUNNER_OPTION", "codex")
    assert runner.resolve_runner(None) == "codex"


def test_empty_values_count_as_unset(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_RUNNER", "")
    monkeypatch.setenv("MEM_RUNNER_OPTION", "codex")
    assert runner.resolve_runner("") == "codex"


@pytest.mark.parametrize(
    ("flag", "env", "source"),
    [
        ("gpt", None, "--runner"),
        (None, "MEM_RUNNER", "MEM_RUNNER"),
        (None, "MEM_RUNNER_OPTION", "MEM_RUNNER_OPTION"),
    ],
)
def test_invalid_names_its_source(
    clean: Path, monkeypatch: pytest.MonkeyPatch, flag: str | None, env: str | None, source: str
) -> None:
    if env:
        monkeypatch.setenv(env, "bad")
    with pytest.raises(ValueError, match=source):
        runner.resolve_runner(flag)


def test_invalid_in_config_file(clean: Path) -> None:
    conf = clean / "mem-config" / "agent-memory"
    conf.mkdir(parents=True)
    (conf / "runner").write_text("bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="config file"):
        runner.resolve_runner(None)


def test_find_codex_env_first(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_CODEX", "/x/codex")
    assert runner.find_codex() == "/x/codex"


def test_find_codex_on_path_before_extension(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    on_path = codex_file(clean / "bin" / "codex")
    codex_file(
        clean
        / "home"
        / ".vscode"
        / "extensions"
        / "openai.chatgpt-1.0.0-linux-x64"
        / "bin"
        / "linux-x64"
        / "codex"
    )
    monkeypatch.setenv("PATH", str(clean / "bin"))
    assert runner.find_codex() == str(on_path)


def test_find_codex_newest_extension(clean: Path) -> None:
    ext = clean / "home" / ".vscode" / "extensions"
    codex_file(ext / "openai.chatgpt-26.999.1-linux-x64" / "bin" / "linux-x64" / "codex")
    newest = codex_file(
        ext / "openai.chatgpt-26.1120.41243-linux-x64" / "bin" / "linux-x64" / "codex"
    )
    other = (
        clean
        / "home"
        / ".vscode-server"
        / "extensions"
        / "openai.chatgpt-27.1.1-linux-x64"
        / "bin"
        / "linux-x64"
        / "codex"
    )
    other.parent.mkdir(parents=True)
    other.write_text("", encoding="utf-8")  # not executable: skipped
    assert runner.find_codex() == str(newest)


def test_find_codex_none(clean: Path) -> None:
    assert runner.find_codex() is None


def session(model: str = "sonnet", effort: str | None = "high") -> headless.Session:
    return headless.Session(
        "claude",
        "p",
        model,
        Path("/s.json"),
        effort=effort,
        tools=("Bash",),
        allowed=("Bash(mem x)",),
        disallowed=("Write",),
        max_budget=1.0,
        agent="a",
        plugin_dir=Path("/pl"),
    )


def test_codex_command_read_only(tmp_path: Path) -> None:
    assert runner.codex_command(session(), "/c/codex", tmp_path, writes=False) == [
        "/c/codex", "exec", "--json", "--ephemeral", "--ignore-user-config", "--disable", "hooks",
        "--skip-git-repo-check", "-s", "read-only", "-C", str(tmp_path), "-m", "gpt-6.1-terra",
        "-c", "model_reasoning_effort=medium", "-",
    ]  # fmt: skip


def test_codex_command_writes(tmp_path: Path) -> None:
    cmd = runner.codex_command(session("haiku", "low"), "codex", tmp_path, writes=True)
    assert cmd[cmd.index("-s") + 1] == "workspace-write"
    assert cmd[cmd.index("-m") + 1] == "gpt-6-luna"
    assert cmd[-3:] == ["-c", "model_reasoning_effort=low", "-"]


def test_codex_env(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_bin = clean / "realbin"
    real_bin.mkdir()
    (real_bin / "mem").write_text("", encoding="utf-8")
    (real_bin / "mem").chmod(0o755)
    monkeypatch.setenv("PATH", f"{real_bin}{os.pathsep}/usr/bin")
    monkeypatch.setenv("MEM_STORE", "/store")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/p")
    run = clean / "run"
    env = runner.codex_env(run)
    assert env["CODEX_HOME"] == str(clean / "home" / ".codex")
    assert env["HOME"] == str(run / "home")
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        assert Path(env[var]).is_relative_to(run)
    assert not [k for k in env if k.startswith(("MEM_", "CLAUDE_PLUGIN"))]
    assert str(real_bin) not in env["PATH"].split(os.pathsep)


def test_codex_env_keeps_explicit_codex_home(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_HOME", "/elsewhere")
    assert runner.codex_env(clean / "run")["CODEX_HOME"] == "/elsewhere"


def stream(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


MESSAGE = {"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}
FINAL = {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}
COMMAND = {
    "type": "item.completed",
    "item": {"type": "command_execution", "command": "ls", "exit_code": 2},
}
TOKENS = 107
USAGE = {
    "input_tokens": 100,
    "cached_input_tokens": 80,
    "output_tokens": 7,
    "reasoning_output_tokens": 3,
}
COMPLETED = {"type": "turn.completed", "usage": USAGE}


def test_parse_codex_success() -> None:
    out = runner.parse_codex(
        stream({"type": "thread.started"}, MESSAGE, COMMAND, FINAL, COMPLETED), 0
    )
    assert out == runner.Outcome(True, "done", TOKENS, 0.0, [("ls", 2)], "")


def test_parse_codex_turn_failed() -> None:
    failed = {"type": "turn.failed", "error": {"message": "boom"}}
    out = runner.parse_codex(stream(MESSAGE, {"type": "error", "message": "net"}, failed), 1)
    assert not out.has_result
    assert out.error == "net; boom"


def test_parse_codex_truncated_by_timeout() -> None:
    out = runner.parse_codex(stream(MESSAGE) + '{"type": "turn.compl', None)
    assert not out.has_result
    assert out.text == "first"
    assert out.error == "the session did not complete"


def test_parse_codex_no_agent_message() -> None:
    out = runner.parse_codex(stream(COMPLETED), 0)
    assert not out.has_result
    assert out.error == "no final message"
    assert out.tokens == TOKENS


def test_parse_codex_nonzero_exit_is_not_a_result() -> None:
    assert not runner.parse_codex(stream(FINAL, COMPLETED), 3).has_result


def test_claude_outcome() -> None:
    final = {
        "type": "result", "result": "ok", "is_error": False, "total_cost_usd": 0.25,
        "usage": {"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 99, "output_tokens": 2},
    }  # fmt: skip
    assert runner.claude_outcome(stream({"type": "assistant"}, final)) == runner.Outcome(
        True, "ok", 17, 0.25
    )


def test_claude_outcome_error_and_missing() -> None:
    bad = runner.claude_outcome(stream({"type": "result", "result": "limit", "is_error": True}))
    assert bad.has_result
    assert bad.error == "limit"
    assert runner.claude_outcome("not json\n") == runner.Outcome(False, error="no result event")


def test_run_codex_passes_prompt_on_stdin(tmp_path: Path) -> None:
    raw = runner.run_codex(
        ["cat"], "hello", cwd=tmp_path, env={"PATH": os.environ.get("PATH", "")}, timeout=30
    )
    assert raw == runner.CodexRaw("hello", False, 0)


def test_run_codex_timeout_keeps_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def expire(cmd: list[str], **kwargs: object) -> None:
        assert kwargs["input"] == "p"
        raise subprocess.TimeoutExpired(cmd, 1, output=b"partial \xe2\x82")

    monkeypatch.setattr(subprocess, "run", expire)
    raw = runner.run_codex(["codex"], "p", cwd=tmp_path, env={}, timeout=1)
    assert raw == runner.CodexRaw("partial ", True, None)
