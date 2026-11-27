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
    mine = codex_file(clean / "mine" / "codex")
    monkeypatch.setenv("MEM_CODEX", str(mine))
    assert runner.find_codex() == str(mine)


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
    assert env["HOME"] == str(run / "home")
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        assert Path(env[var]).is_relative_to(run)
    assert not [k for k in env if k.startswith(("MEM_", "CLAUDE_PLUGIN"))]
    assert str(real_bin) not in env["PATH"].split(os.pathsep)


def test_codex_home_is_clean_with_only_an_auth_symlink(
    clean: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = clean / "home" / ".codex"
    real.mkdir(parents=True)
    (real / "auth.json").write_text("{}", encoding="utf-8")
    (real / "AGENTS.md").write_text("owner rules", encoding="utf-8")
    run = clean / "run"
    home = Path(runner.codex_env(run)["CODEX_HOME"])
    assert home == run / "codex-home"
    assert stat.S_IMODE(home.stat().st_mode) == runner.PRIVATE_MODE
    assert [p.name for p in home.iterdir()] == ["auth.json"]
    assert (home / "auth.json").is_symlink()
    assert (home / "auth.json").readlink() == real / "auth.json"
    runner.codex_env(run)  # a second call keeps the same folder


def test_codex_home_uses_an_explicit_real_codex_home(
    clean: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = clean / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(elsewhere))
    env = runner.codex_env(clean / "run")
    assert (Path(env["CODEX_HOME"]) / "auth.json").readlink() == elsewhere / "auth.json"


def test_codex_home_without_a_real_auth_has_no_link(clean: Path) -> None:
    home = Path(runner.codex_env(clean / "run")["CODEX_HOME"])
    assert home.is_dir()
    assert list(home.iterdir()) == []


def test_unmapped_pair_names_it() -> None:
    with pytest.raises(ValueError, match=r"opus.*max"):
        runner.codex_command(session("opus", "max"), "codex", Path("/r"), writes=False)


def test_no_effort_maps_to_medium() -> None:
    assert runner.codex_model(session("sonnet", None)) == ("gpt-6.1-terra", "low")


def test_mem_codex_missing_or_not_executable_falls_through(
    clean: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEM_CODEX", str(clean / "nope"))
    assert runner.find_codex() is None
    plain = clean / "plain"
    plain.write_text("", encoding="utf-8")
    monkeypatch.setenv("MEM_CODEX", str(plain))
    on_path = codex_file(clean / "emptybin" / "codex")
    assert runner.find_codex() == str(on_path)


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
    assert not runner.parse_codex(
        stream(MESSAGE, {"type": "error", "message": "x"}, FINAL, COMPLETED), 0
    ).error


def test_parse_codex_turn_failed() -> None:
    failed = {"type": "turn.failed", "error": {"message": "boom"}}
    out = runner.parse_codex(stream(MESSAGE, {"type": "error", "message": "net"}, failed), 1)
    assert not out.has_result
    assert out.error == "net; boom; exit 1"


def test_parse_codex_truncated_by_timeout() -> None:
    out = runner.parse_codex(stream(MESSAGE) + '{"type": "turn.compl', None, timed_out=True)
    assert not out.has_result
    assert out.text == "first"
    assert out.error == "the session timed out"


def test_parse_codex_no_agent_message() -> None:
    out = runner.parse_codex(stream(COMPLETED), 0)
    assert not out.has_result
    assert out.error == "no final message"
    assert out.tokens == TOKENS


def test_parse_codex_nonzero_exit_is_not_a_result() -> None:
    assert not runner.parse_codex(stream(FINAL, COMPLETED), 3).has_result


def test_parse_codex_error_carries_the_last_stderr_lines() -> None:
    err = "\n".join(f"line {n}" for n in range(9)) + "\nerror: unknown flag\n"
    out = runner.parse_codex("", 2, err)
    assert out.error.startswith("the session did not complete; exit 2; stderr: ")
    assert out.error.endswith("line 8 | error: unknown flag")
    assert "line 3" not in out.error


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
    assert not bad.has_result
    assert bad.error == "limit"
    assert runner.claude_outcome("not json\n") == runner.Outcome(False, error="no result event")


def test_run_codex_passes_prompt_on_stdin(tmp_path: Path) -> None:
    raw = runner.run_codex(
        ["cat"], "hello", cwd=tmp_path, env={"PATH": os.environ.get("PATH", "")}, timeout=30
    )
    assert raw == runner.CodexRaw("hello", False, 0, "")


def test_run_codex_captures_stderr_and_decodes_utf8(tmp_path: Path) -> None:
    cmd = ["sh", "-c", "printf '\\303\\251 \\377'; printf 'bad flag' >&2; exit 2"]
    raw = runner.run_codex(
        cmd, "", cwd=tmp_path, env={"PATH": os.environ.get("PATH", "")}, timeout=30
    )
    assert raw == runner.CodexRaw("\u00e9 \ufffd", False, 2, "bad flag")


def test_run_codex_timeout_keeps_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def expire(cmd: list[str], **kwargs: object) -> None:
        assert kwargs["input"] == "p"
        raise subprocess.TimeoutExpired(cmd, 1, output=b"partial \xe2\x82", stderr=b"slow")

    monkeypatch.setattr(subprocess, "run", expire)
    raw = runner.run_codex(["codex"], "p", cwd=tmp_path, env={}, timeout=1)
    assert raw == runner.CodexRaw("partial ", True, None, "slow")


def _auth_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """(run folder, real auth.json, the per-run auth.json) with the real file holding an old token."""
    real_home = tmp_path / "codex"
    real_home.mkdir()
    real = real_home / "auth.json"
    real.write_text('{"token": "old"}', encoding="utf-8")
    os.utime(real, (1, 1))
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    run_dir = tmp_path / "run"
    runner.codex_env(run_dir)
    return run_dir, real, run_dir / "codex-home" / "auth.json"


def _replace_auth(fresh: Path, content: str) -> None:
    tmp = fresh.with_name("auth.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(fresh)  # write-temp-then-rename: the symlink becomes a regular file


def test_sync_auth_in_place_write_needs_no_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, real, fresh = _auth_world(tmp_path, monkeypatch)
    fresh.write_text('{"token": "new"}', encoding="utf-8")  # through the link
    assert fresh.is_symlink()
    assert runner.sync_auth(run_dir) is False
    assert json.loads(real.read_text(encoding="utf-8")) == {"token": "new"}


def test_sync_auth_rename_replace_updates_the_real_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, real, fresh = _auth_world(tmp_path, monkeypatch)
    _replace_auth(fresh, '{"token": "new"}')
    assert runner.sync_auth(run_dir) is True
    assert json.loads(real.read_text(encoding="utf-8")) == {"token": "new"}
    assert (
        stat.S_IMODE(real.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR and not real.is_symlink()
    )
    assert [p.name for p in real.parent.iterdir()] == ["auth.json"]


def test_sync_auth_ignores_invalid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir, real, fresh = _auth_world(tmp_path, monkeypatch)
    _replace_auth(fresh, "{not json")
    assert runner.sync_auth(run_dir) is False
    assert json.loads(real.read_text(encoding="utf-8")) == {"token": "old"}


def test_sync_auth_ignores_an_older_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir, real, fresh = _auth_world(tmp_path, monkeypatch)
    _replace_auth(fresh, '{"token": "new"}')
    os.utime(fresh, (1, 1))
    os.utime(real, (5, 5))
    assert runner.sync_auth(run_dir) is False
    assert json.loads(real.read_text(encoding="utf-8")) == {"token": "old"}


def test_sync_auth_refuses_a_symlinked_real_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, real, fresh = _auth_world(tmp_path, monkeypatch)
    target = tmp_path / "elsewhere.json"
    target.write_text('{"token": "old"}', encoding="utf-8")
    real.unlink()
    real.symlink_to(target)
    _replace_auth(fresh, '{"token": "new"}')
    assert runner.sync_auth(run_dir) is False
    assert json.loads(target.read_text(encoding="utf-8")) == {"token": "old"}
