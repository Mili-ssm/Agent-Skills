"""Golden command lines, environments and runner arguments of the seven headless `claude -p` sessions, as built at
plan base (A2). Every expected value is a literal written from the builders' output, never computed by the code under
test: a refactor that moves the builders must leave these untouched, except where its plan lists a flag addition."""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import corroborate_run
import headless
import pytest
import research_pipeline
from synthesize import pipeline as synth_pipeline
from synthesize import references as backfill
from synthesize import run as sr

PLUGIN = Path(__file__).resolve().parents[2]
BUDGET = 0.25
PROMPT = "the prompt"
CLAUDE = "claude"
EMPTY = ""
WORK_PLACEHOLDER = "{work}"
SESSION_TIMEOUT = 600  # corroborate, mem-capture, mem-settle
BACKFILL_TIMEOUT = 900
SYNTH_TIMEOUT = 1500  # the default of synthesize.pipeline.run_session
CUSTOM_TIMEOUT = 77
RESEARCH_MIN_TIMEOUT = 1.0  # research: max(1.0, seconds left), pinned with no time left
SESSION_VARS = (
    "CLAUDE_ENV_FILE",
    "CLAUDE_PLUGIN_ROOT",
    "CLAUDE_PLUGIN_DATA",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_PID",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
)


def flag_map(argv: list[str]) -> dict[str, tuple[str, ...]]:
    """Flag (a token starting with `--`) -> the tokens after it up to the next flag; a repeated flag fails."""
    found: dict[str, tuple[str, ...]] = {}
    flag = None
    values: list[str] = []
    for token in [*argv, "--"]:
        if token.startswith("--"):
            if flag is not None:
                assert flag not in found, f"{flag} appears twice"
                found[flag] = tuple(values)
            flag, values = token, []
        else:
            assert flag is not None, f"{token!r} comes before the first flag"
            values.append(token)
    return found


def load_bin(name: str) -> ModuleType:
    path = PLUGIN / "bin" / name
    loader = importlib.machinery.SourceFileLoader(f"golden_{name.replace('-', '_')}", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mem_capture() -> ModuleType:
    return load_bin("mem-capture")


@pytest.fixture(scope="module")
def mem_settle() -> ModuleType:
    return load_bin("mem-settle")


@pytest.fixture(scope="module")
def mem_synthesize() -> ModuleType:
    return sr


class Recorder:
    """A stand-in for `subprocess.run`: records every call and answers with an empty stdout."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        self.calls.append((cmd, kwargs))
        return SimpleNamespace(stdout="")

    @property
    def cmd(self) -> list[str]:
        return self.calls[-1][0]

    @property
    def kwargs(self) -> dict[str, Any]:
        return self.calls[-1][1]


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    return recorder


def raising(exc: BaseException):
    def fake(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        raise exc

    return fake


# ---- command lines ----


def test_flag_map_reads_values_and_refuses_a_repeated_flag() -> None:
    assert flag_map(["--a", "1", "2", "--b", "--c", "3"]) == {
        "--a": ("1", "2"),
        "--b": (),
        "--c": ("3",),
    }
    with pytest.raises(AssertionError, match="--a appears twice"):
        flag_map(["--a", "1", "--a", "2"])


def test_corroborate_command_line(tmp_path: Path) -> None:
    work, settings = tmp_path / "work", tmp_path / "settings.json"
    argv = corroborate_run.session_cmd(
        CLAUDE, work, PROMPT, settings, corroborate_run.SessionLimits("haiku", BUDGET)
    )
    assert argv[:3] == ["claude", "-p", "the prompt"]
    assert flag_map(argv[3:]) == {
        "--model": ("haiku",),
        "--effort": ("medium",),
        "--settings": (str(settings),),
        "--setting-sources": ("project",),
        "--tools": ("Read,Write",),
        "--strict-mcp-config": (),
        "--allowedTools": (f"Read(/{work}/**)", f"Write(/{work}/**)", f"Edit(/{work}/**)"),
        "--disallowedTools": ("Bash", "WebSearch", "WebFetch"),
        "--output-format": ("stream-json",),
        "--verbose": (),
        "--no-session-persistence": (),
        "--max-budget-usd": ("0.2500",),
    }


def test_capture_command_line(mem_capture: ModuleType, tmp_path: Path) -> None:
    work, settings = tmp_path / "work", tmp_path / "settings.json"
    argv = mem_capture.session_cmd(CLAUDE, work, settings, "haiku", BUDGET)
    assert argv[:2] == ["claude", "-p"]
    assert argv[2].startswith("You read the record of one coding session")
    assert f"Files in {work}:" in argv[2]
    assert WORK_PLACEHOLDER not in argv[2]
    assert flag_map(argv[3:]) == {
        "--model": ("haiku",),
        "--effort": ("medium",),
        "--settings": (str(settings),),
        "--setting-sources": ("project",),
        "--tools": ("Read,Write",),
        "--strict-mcp-config": (),
        "--allowedTools": (f"Read(/{work}/**)", f"Write(/{work}/**)", f"Edit(/{work}/**)"),
        "--disallowedTools": ("Bash", "WebSearch", "WebFetch"),
        "--output-format": ("stream-json",),
        "--verbose": (),
        "--no-session-persistence": (),
        "--max-budget-usd": ("0.2500",),
    }


def test_settle_command_line(mem_settle: ModuleType, tmp_path: Path) -> None:
    work, settings = tmp_path / "work", tmp_path / "settings.json"
    argv = mem_settle.session_cmd(CLAUDE, work, PROMPT, settings, BUDGET)
    assert argv[:3] == ["claude", "-p", "the prompt"]
    assert flag_map(argv[3:]) == {
        "--model": ("haiku",),
        "--effort": ("medium",),
        "--settings": (str(settings),),
        "--setting-sources": ("project",),
        "--strict-mcp-config": (),
        "--allowedTools": (f"Read(/{work}/**)", f"Write(/{work}/**)", f"Edit(/{work}/**)"),
        "--disallowedTools": ("Bash", "WebSearch", "WebFetch"),
        "--output-format": ("stream-json",),
        "--verbose": (),
        "--no-session-persistence": (),
        "--max-budget-usd": ("0.2500",),
    }


SYNTH_MEM_ALLOWED = (
    "Bash(mem curate*)",
    "Bash(mem show*)",
    "Bash(mem memories*)",
    "Bash(mem search*)",
    "Bash(mem find*)",
    "Bash(mem check*)",
    "Bash(mem synthesis list*)",
    "Bash(mem synthesis new*)",
    "Bash(mem synthesis add*)",
    "Bash(mem synthesis append*)",
    "Bash(mem synthesis edit*)",
)


def test_synthesis_command_line_minimal(run: Recorder, tmp_path: Path) -> None:
    work, settings, store = tmp_path / "work", tmp_path / "settings.json", tmp_path / "store"
    synth_pipeline.run_session(
        CLAUDE,
        "haiku",
        PROMPT,
        work,
        settings,
        env={},
        log=tmp_path / "log",
        read_roots=[store],
    )
    skill_dir = PLUGIN / "skills" / "memory-synthesis"
    assert run.cmd[:3] == ["claude", "-p", "the prompt"]
    assert flag_map(run.cmd[3:]) == {
        "--model": ("haiku",),
        "--plugin-dir": (str(PLUGIN),),
        "--settings": (str(settings),),
        "--setting-sources": ("project",),
        "--strict-mcp-config": (),
        "--allowedTools": (
            *SYNTH_MEM_ALLOWED,
            f"Read(/{store}/**)",
            f"Grep(/{store}/**)",
            f"Glob(/{store}/**)",
            f"Read(/{skill_dir}/**)",
            f"Grep(/{skill_dir}/**)",
            f"Glob(/{skill_dir}/**)",
            f"Write(/{work}/**)",
            f"Edit(/{work}/**)",
        ),
        "--disallowedTools": ("WebSearch", "WebFetch"),
        "--output-format": ("stream-json",),
        "--verbose": (),
        "--no-session-persistence": (),
    }


def test_synthesis_command_line_with_effort_budget_and_agent(run: Recorder, tmp_path: Path) -> None:
    work, settings = tmp_path / "work", tmp_path / "settings.json"
    synth_pipeline.run_session(
        CLAUDE,
        "sonnet",
        PROMPT,
        work,
        settings,
        env={},
        log=tmp_path / "log",
        effort="high",
        agent="curator",
        max_budget=BUDGET,
    )
    skill_dir = PLUGIN / "skills" / "memory-synthesis"
    assert run.cmd[:3] == ["claude", "-p", "the prompt"]
    assert flag_map(run.cmd[3:]) == {
        "--model": ("sonnet",),
        "--plugin-dir": (str(PLUGIN),),
        "--settings": (str(settings),),
        "--setting-sources": ("project",),
        "--strict-mcp-config": (),
        "--allowedTools": (
            *SYNTH_MEM_ALLOWED,
            f"Read(/{skill_dir}/**)",
            f"Grep(/{skill_dir}/**)",
            f"Glob(/{skill_dir}/**)",
            f"Write(/{work}/**)",
            f"Edit(/{work}/**)",
        ),
        "--disallowedTools": ("WebSearch", "WebFetch"),
        "--output-format": ("stream-json",),
        "--verbose": (),
        "--no-session-persistence": (),
        "--effort": ("high",),
        "--max-budget-usd": ("0.2500",),
        "--agent": ("curator",),
    }


def test_research_file_command_line(tmp_path: Path) -> None:
    work, settings = tmp_path / "work", tmp_path / "settings.json"
    argv = research_pipeline.file_cmd(CLAUDE, PROMPT, work, settings, BUDGET)
    assert argv[:3] == ["claude", "-p", "the prompt"]
    assert flag_map(argv[3:]) == {
        "--model": ("haiku",),
        "--effort": ("medium",),
        "--settings": (str(settings),),
        "--setting-sources": ("project",),
        "--tools": ("Read,Write,Edit",),
        "--strict-mcp-config": (),
        "--allowedTools": (f"Read(/{work}/**)", f"Write(/{work}/**)", f"Edit(/{work}/**)"),
        "--output-format": ("stream-json",),
        "--verbose": (),
        "--no-session-persistence": (),
        "--max-budget-usd": ("0.2500",),
    }


def test_research_web_command_line(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    argv = research_pipeline.web_cmd(CLAUDE, PROMPT, settings, BUDGET)
    assert argv[:3] == ["claude", "-p", "the prompt"]
    assert flag_map(argv[3:]) == {
        "--model": ("haiku",),
        "--effort": ("medium",),
        "--settings": (str(settings),),
        "--setting-sources": ("project",),
        "--tools": ("WebSearch,WebFetch",),
        "--strict-mcp-config": (),
        "--allowedTools": ("WebSearch", "WebFetch"),
        "--output-format": ("stream-json",),
        "--verbose": (),
        "--no-session-persistence": (),
        "--max-budget-usd": ("0.2500",),
    }


def test_backfill_command_line(tmp_path: Path) -> None:
    work, store, settings = tmp_path / "work", tmp_path / "store", tmp_path / "settings.json"
    argv = backfill.session_cmd(CLAUDE, PROMPT, work, store, settings=settings, max_budget=BUDGET)
    assert argv[:3] == ["claude", "-p", "the prompt"]
    assert flag_map(argv[3:]) == {
        "--model": ("haiku",),
        "--effort": ("high",),
        "--settings": (str(settings),),
        "--setting-sources": ("project",),
        "--tools": ("Read",),
        "--strict-mcp-config": (),
        "--allowedTools": (f"Read(/{work}/**)", f"Read(/{store}/**)"),
        "--output-format": ("stream-json",),
        "--verbose": (),
        "--no-session-persistence": (),
        "--max-budget-usd": ("0.2500",),
    }


def test_backfill_command_line_without_a_budget(tmp_path: Path) -> None:
    argv = backfill.session_cmd(
        CLAUDE,
        PROMPT,
        tmp_path / "w",
        tmp_path / "s",
        settings=tmp_path / "x.json",
        max_budget=None,
    )
    assert "--max-budget-usd" not in argv


# ---- environments ----


@pytest.fixture
def crafted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """An environment holding a MEM_ variable, every plugin and session variable, one that must survive, and a PATH
    with a folder that holds an executable `mem`, a folder of the installed plugin cache and a plain folder."""
    with_mem, cache, plain = (
        tmp_path / "withmem",
        tmp_path / "plugins" / "cache" / "x",
        tmp_path / "plain",
    )
    for folder in (with_mem, cache, plain):
        folder.mkdir(parents=True)
    (with_mem / "mem").write_text("#!/bin/sh\n")
    (with_mem / "mem").chmod(0o755)
    path = os.pathsep.join([str(with_mem), "", str(cache), str(plain)])
    values = {
        "MEM_X": "1",
        "CLAUDE_PLUGIN_OPTION_Y": "2",
        "KEEP_ME": "3",
        **dict.fromkeys(SESSION_VARS, "v"),
        "PATH": path,
    }
    for name in ("MEM_STORE", "MEM_MEMORIES", "MEM_PROJECT"):
        values[name] = "m"
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return {"with_mem": str(with_mem), "cache": str(cache), "plain": str(plain)}


def test_research_session_env(crafted: dict[str, str]) -> None:
    env = headless.session_env()
    assert env["KEEP_ME"] == "3"
    for gone in (
        "MEM_X",
        "MEM_STORE",
        "MEM_MEMORIES",
        "MEM_PROJECT",
        "CLAUDE_PLUGIN_ROOT",
        "CLAUDE_PLUGIN_DATA",
        "CLAUDE_PLUGIN_OPTION_Y",
        "CLAUDE_ENV_FILE",
        "CLAUDE_PROJECT_DIR",
        "CLAUDE_PID",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_MESSAGING_SOCKET",
        "CLAUDE_CODE_MESSAGING_TOKEN",
    ):
        assert gone not in env
    # The folder with `mem` and the empty entry go; the plugin cache folder stays (it holds no `mem`).
    assert env["PATH"] == os.pathsep.join([crafted["cache"], crafted["plain"]])


def test_capture_session_env(
    mem_capture: ModuleType, run: Recorder, crafted: dict[str, str], tmp_path: Path
) -> None:
    mem_capture.run_session(["claude"], tmp_path)
    env = run.kwargs["env"]
    for gone in SESSION_VARS:
        assert gone not in env
    for kept in (
        "MEM_X",
        "MEM_STORE",
        "MEM_MEMORIES",
        "MEM_PROJECT",
        "CLAUDE_PLUGIN_OPTION_Y",
        "KEEP_ME",
    ):
        assert kept in env
    assert env["PATH"] == os.environ["PATH"]
    assert crafted["with_mem"] in env["PATH"].split(os.pathsep)


def test_synthesize_session_env(
    mem_synthesize: ModuleType, crafted: dict[str, str], tmp_path: Path
) -> None:
    store = tmp_path / "store"
    env = mem_synthesize.session_env(store)
    for gone in ("MEM_MEMORIES", "MEM_PROJECT", "CLAUDE_PLUGIN_OPTION_Y"):
        assert gone not in env
    for kept in ("MEM_X", "KEEP_ME", *SESSION_VARS):
        assert kept in env
    assert env["MEM_STORE"] == str(store)
    # The installed plugin's cache folder leaves PATH; the folder with `mem` and the empty entry stay.
    assert env["PATH"] == os.pathsep.join([crafted["with_mem"], "", crafted["plain"]])


def test_synthesis_session_adds_the_sandbox_variables_and_leaves_the_callers_env(
    run: Recorder, tmp_path: Path
) -> None:
    store, memories = tmp_path / "store", tmp_path / "memories"
    caller_env = {"MEM_STORE": str(store), "KEEP_ME": "3"}
    synth_pipeline.run_session(
        CLAUDE,
        "haiku",
        PROMPT,
        tmp_path / "work",
        tmp_path / "settings.json",
        env=caller_env,
        log=tmp_path / "log",
        read_roots=[store, memories],
    )
    assert run.kwargs["env"] == {
        "MEM_STORE": str(store),
        "KEEP_ME": "3",
        "MEM_SANDBOX": "1",
        "MEM_SANDBOX_ROOTS": f"{store}{os.pathsep}{memories}",
    }
    assert caller_env == {"MEM_STORE": str(store), "KEEP_ME": "3"}


def test_synthesis_session_without_roots_sets_empty_sandbox_roots(
    run: Recorder, tmp_path: Path
) -> None:
    synth_pipeline.run_session(
        CLAUDE,
        "haiku",
        PROMPT,
        tmp_path,
        tmp_path / "s.json",
        env={},
        log=tmp_path / "log",
    )
    assert run.kwargs["env"] == {"MEM_SANDBOX": "1", "MEM_SANDBOX_ROOTS": ""}


# ---- runner keyword arguments ----


def test_corroborate_runner_arguments(run: Recorder, tmp_path: Path) -> None:
    corroborate_run.run_session(["claude", "-p", "x"], tmp_path)
    assert run.cmd == ["claude", "-p", "x"]
    kwargs = dict(run.kwargs)
    env = kwargs.pop("env")
    assert isinstance(env, dict)
    assert kwargs == {
        "cwd": tmp_path,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "timeout": SESSION_TIMEOUT,
        "check": False,
    }


def test_corroborate_session_env(run: Recorder, crafted: dict[str, str], tmp_path: Path) -> None:
    corroborate_run.run_session(["claude"], tmp_path)
    env = run.kwargs["env"]
    for gone in ("MEM_X", "MEM_STORE", "CLAUDE_PLUGIN_OPTION_Y"):
        assert gone not in env
    assert "KEEP_ME" in env
    assert crafted["with_mem"] not in env["PATH"].split(os.pathsep)


def test_capture_runner_arguments(mem_capture: ModuleType, run: Recorder, tmp_path: Path) -> None:
    mem_capture.run_session(["claude", "-p", "x"], tmp_path)
    kwargs = dict(run.kwargs)
    assert isinstance(kwargs.pop("env"), dict)
    assert kwargs == {
        "cwd": tmp_path,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": SESSION_TIMEOUT,
        "check": False,
    }


def test_settle_runner_arguments(mem_settle: ModuleType, run: Recorder, tmp_path: Path) -> None:
    env = {"E": "1"}
    cmd = mem_settle.session_cmd(CLAUDE, tmp_path, PROMPT, tmp_path / "settings.json", BUDGET)
    mem_settle.session(cmd, tmp_path, env, tmp_path / "log")
    assert run.cmd[:3] == ["claude", "-p", "the prompt"]
    assert run.kwargs == {
        "cwd": tmp_path,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": SESSION_TIMEOUT,
        "check": False,
    }


def test_synthesis_runner_arguments(run: Recorder, tmp_path: Path) -> None:
    env = {"E": "1"}
    synth_pipeline.run_session(
        CLAUDE,
        "haiku",
        PROMPT,
        tmp_path,
        tmp_path / "s.json",
        env=env,
        log=tmp_path / "log",
    )
    assert run.kwargs == {
        "cwd": tmp_path,
        "env": {"E": "1", "MEM_SANDBOX": "1", "MEM_SANDBOX_ROOTS": ""},
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": SYNTH_TIMEOUT,
        "check": False,
    }
    synth_pipeline.run_session(
        CLAUDE,
        "haiku",
        PROMPT,
        tmp_path,
        tmp_path / "s.json",
        env=env,
        log=tmp_path / "log",
        timeout=CUSTOM_TIMEOUT,
    )
    assert run.kwargs["timeout"] == CUSTOM_TIMEOUT


def test_backfill_runner_arguments(run: Recorder, tmp_path: Path) -> None:
    env = {"E": "1"}
    backfill.run_session(["claude", "-p", "x"], tmp_path, env, tmp_path / "log")
    assert run.cmd == ["claude", "-p", "x"]
    assert run.kwargs == {
        "check": False,
        "cwd": tmp_path,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": BACKFILL_TIMEOUT,
    }


def research_run(tmp_path: Path) -> tuple[research_pipeline.Run, Path]:
    folder = tmp_path / "run"
    cwd = folder / "step" / "work"
    cwd.mkdir(parents=True)
    return research_pipeline.Run(folder, BUDGET, 0.0), cwd


def test_research_runner_arguments(run: Recorder, tmp_path: Path) -> None:
    current, cwd = research_run(tmp_path)
    env = {"E": "1"}
    with pytest.raises(research_pipeline.StopError):  # an empty stream has no result: the run stops
        current.session("memory", ["claude", "-p", "x"], cwd, env, PROMPT)
    assert run.cmd == ["claude", "-p", "x"]
    assert run.kwargs == {
        "cwd": cwd,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": RESEARCH_MIN_TIMEOUT,
        "check": False,
    }


# ---- timed-out sessions ----


def test_research_timeout_keeps_the_partial_stream_and_stops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    current, cwd = research_run(tmp_path)
    exc = subprocess.TimeoutExpired(["claude"], 1, output=b"partial text")
    monkeypatch.setattr(subprocess, "run", raising(exc))
    with pytest.raises(research_pipeline.StopError) as caught:
        current.session("memory", ["claude"], cwd, {}, PROMPT)
    assert str(caught.value) == "time limit reached"
    assert (cwd.parent / "session.jsonl").read_text() == "partial text"
    assert (cwd.parent / "brief.txt").read_text() == PROMPT


def test_research_start_failure_stops_with_the_os_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    current, cwd = research_run(tmp_path)
    monkeypatch.setattr(subprocess, "run", raising(OSError("no such file")))
    with pytest.raises(research_pipeline.StopError) as caught:
        current.session("memory", ["claude"], cwd, {}, PROMPT)
    assert str(caught.value) == "cannot start claude: no such file"
    assert (cwd.parent / "session.jsonl").read_text() == EMPTY


RESULT_LINE = b'{"type": "result", "is_error": false, "result": "ok", "total_cost_usd": 0.5}\n'


def test_corroborate_timeout_with_invalid_utf8_returns_the_parsed_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exc = subprocess.TimeoutExpired(["claude"], 1, output=b"\xff\xfe broken\n" + RESULT_LINE)
    monkeypatch.setattr(subprocess, "run", raising(exc))
    result = corroborate_run.run_session(["claude"], tmp_path)
    assert result["has_result"] is True
    assert result["answer"] == "ok"
    assert result["cost"] == pytest.approx(0.5)
