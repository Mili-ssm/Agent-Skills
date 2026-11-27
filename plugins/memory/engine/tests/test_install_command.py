"""`mem install-command` and the plugin-root record it follows (ADR 0036)."""

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import mem
import pytest
from commands import hooks, install

EXEC_MODE = 0o755
NOT_FOUND = 127
HOOKS = Path(__file__).resolve().parents[2] / "hooks"
BASH = shutil.which("bash") or "bash"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("MEM_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no `mem` on PATH
    return h


def _install(bin_dir: Path, *extra: str) -> int:
    return mem.main(["install-command", "--bin-dir", str(bin_dir), *extra])


def _fake_plugin(root: Path, tag: str) -> None:
    (root / "bin").mkdir(parents=True)
    exe = root / "bin" / "mem"
    exe.write_text(f'#!/usr/bin/env bash\necho "{tag}:$*"\n')
    exe.chmod(0o755)


def _run_launcher(launcher: Path, home: Path, tmp_path: Path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "MEM_DATA": str(tmp_path / "data")}
    return subprocess.run(
        [BASH, str(launcher), "a", "b"], env=env, capture_output=True, text=True, check=False
    )


def test_install_writes_an_executable_launcher_with_the_marker(tmp_path, home, capsys):
    bin_dir = tmp_path / "bin"
    assert _install(bin_dir) == 0
    target = bin_dir / "mem"
    assert os.access(target, os.X_OK) and target.stat().st_mode & 0o777 == EXEC_MODE
    assert target.read_text().splitlines()[1] == install.MARKER
    out = capsys.readouterr()
    assert str(target) in out.out and "not on PATH" in out.err
    assert _install(bin_dir) == 0  # idempotent


def test_install_refuses_a_foreign_file_and_remove_keeps_it(tmp_path, home, capsys):
    target = tmp_path / "bin" / "mem"
    target.parent.mkdir()
    target.write_text("#!/bin/sh\necho mine\n")
    assert _install(target.parent) == 1
    assert _install(target.parent, "--remove") == 1
    assert target.read_text() == "#!/bin/sh\necho mine\n"
    assert "not an agent-memory launcher" in capsys.readouterr().err


def test_remove_deletes_our_launcher_and_is_idempotent(tmp_path, home):
    assert _install(tmp_path / "bin") == 0
    assert _install(tmp_path / "bin", "--remove") == 0
    assert not (tmp_path / "bin" / "mem").exists()
    assert _install(tmp_path / "bin", "--remove") == 0


def test_launcher_follows_the_record_then_the_embedded_root_then_fails(tmp_path, home, monkeypatch):
    embedded, recorded = tmp_path / "embedded", tmp_path / "recorded"
    _fake_plugin(embedded, "embedded")
    _fake_plugin(recorded, "recorded")
    monkeypatch.setattr(install, "plugin_root", lambda: embedded)
    assert _install(tmp_path / "bin") == 0
    launcher = tmp_path / "bin" / "mem"
    (tmp_path / "data").mkdir()
    record = tmp_path / "data" / install.RECORD_NAME
    record.write_text(str(recorded))
    assert _run_launcher(launcher, home, tmp_path).stdout == "recorded:a b\n"
    shutil.rmtree(recorded)  # the record points at a removed copy
    assert _run_launcher(launcher, home, tmp_path).stdout == "embedded:a b\n"
    shutil.rmtree(embedded)
    r = _run_launcher(launcher, home, tmp_path)
    assert r.returncode == NOT_FOUND and "mem: no plugin copy found" in r.stderr
    assert f"{embedded}/bin/mem install-command" in r.stderr


def test_launcher_reads_the_record_from_xdg_state_without_mem_data(tmp_path, home):
    recorded = tmp_path / "recorded"
    _fake_plugin(recorded, "recorded")
    assert _install(tmp_path / "bin") == 0
    state = tmp_path / "xdg" / "agent-memory"
    state.mkdir(parents=True)
    (state / install.RECORD_NAME).write_text(str(recorded))
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "XDG_STATE_HOME": str(tmp_path / "xdg")}
    r = subprocess.run(
        [BASH, str(tmp_path / "bin" / "mem"), "x"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.stdout == "recorded:x\n"


def test_record_root_writes_once_and_skips_a_symlink(tmp_path, home, monkeypatch):
    record = tmp_path / "data" / install.RECORD_NAME
    install.record_root()
    assert record.read_text() == str(install.plugin_root())
    ino = record.stat().st_ino
    install.record_root()
    assert record.stat().st_ino == ino  # unchanged content: not rewritten
    record.unlink()
    victim = tmp_path / "victim"
    victim.write_text("keep")
    record.symlink_to(victim)
    install.record_root()
    assert victim.read_text() == "keep" and record.is_symlink()


def test_record_root_never_raises(tmp_path, home, monkeypatch):
    (tmp_path / "data").write_text("a file where the folder should be")
    assert install.record_root() is None
    assert (tmp_path / "data").read_text() == "a file where the folder should be"


def test_record_root_refuses_a_symlinked_state_folder(tmp_path, home):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "data").symlink_to(elsewhere)
    install.record_root()
    assert list(elsewhere.iterdir()) == []


def _run_guarded(launcher: Path, home: Path, tmp_path: Path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "MEM_DATA": str(tmp_path / "data")}
    return subprocess.run(
        ["timeout", "5", BASH, str(launcher)], env=env, capture_output=True, text=True, check=False
    )


def test_launcher_skips_a_candidate_that_loops_back_to_itself(tmp_path, home, monkeypatch):
    root = tmp_path / "root"
    (root / "bin").mkdir(parents=True)
    monkeypatch.setattr(install, "plugin_root", lambda: root)
    assert _install(tmp_path / "bin") == 0
    launcher = tmp_path / "bin" / "mem"
    (root / "bin" / "mem").symlink_to(launcher)  # same file as the running launcher
    assert _run_guarded(launcher, home, tmp_path).returncode == NOT_FOUND
    (root / "bin" / "mem").unlink()  # a copy of the launcher: carries the marker
    shutil.copy(launcher, root / "bin" / "mem")
    assert _run_guarded(launcher, home, tmp_path).returncode == NOT_FOUND


def test_launcher_survives_a_root_with_shell_metacharacters(tmp_path, home):
    root = tmp_path / 'we"ird $x `y` z'
    text = install.launcher_text(root)
    launcher = tmp_path / "mem"
    launcher.write_text(text)
    assert subprocess.run([BASH, "-n", str(launcher)], check=False).returncode == 0
    r = _run_guarded(launcher, home, tmp_path)
    assert r.returncode == NOT_FOUND
    assert f"with {root}/bin/mem install-command" in r.stderr


def _codex_text(monkeypatch, capsys) -> str:
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert mem.main(["session-index", "--hook"]) == 0
    return capsys.readouterr().out


def test_codex_hint_only_for_codex_without_a_launcher(tmp_path, home, monkeypatch, capsys):
    monkeypatch.setenv("MEM_HOST", "codex")
    root = install.plugin_root()
    mem_cmd = shlex.quote(f"{root}/bin/mem")
    hint = f"memory: mem is not installed as a command; run it as {mem_cmd}, or install it once: {mem_cmd} install-command"
    assert hint in _codex_text(monkeypatch, capsys)
    assert _install(home / ".local" / "bin") == 0
    capsys.readouterr()
    assert "not installed as a command" not in _codex_text(monkeypatch, capsys)
    monkeypatch.delenv("MEM_HOST")
    (home / ".local" / "bin" / "mem").unlink()
    assert "not installed as a command" not in _codex_text(monkeypatch, capsys)
    assert hooks._host() == "claude"


def _subagent(env: dict[str, str], script: Path = HOOKS / "subagent-start.sh") -> str:
    r = subprocess.run(
        [str(script)],
        input="",
        env={"PATH": "/usr/bin:/bin", **env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_subagent_start_names_the_plugin_launcher_for_codex_without_mem(tmp_path):
    odd = tmp_path / 'we"ird\\dir'
    (odd / "hooks").mkdir(parents=True)
    script = odd / "hooks" / "subagent-start.sh"
    shutil.copy(HOOKS / "subagent-start.sh", script)
    text = _subagent({"MEM_HOST": "codex"}, script)
    assert f"{odd}/bin/mem search" in text and f"{odd}/bin/mem show" in text
    assert "Do not run mem remember" not in text
    assert "mem search" in _subagent({}, script)  # Claude: the plain text
    assert "mem search" in _subagent(
        {"MEM_HOST": "codex", "PATH": str(_bin_with_mem(tmp_path))}, script
    )


CLAUDE_SUBAGENT_TEXT = (
    "memory: decisions, constraints and pitfalls learned in earlier sessions are in a searchable memory, not in the "
    'files. Before you change or decide anything, if you can run shell commands: mem search "<topic in English>", '
    "then mem show <handle>. Project memories are files in .memory/ at the repository root. A line marked "
    "[memory: ...] is experience, not fact. Do not run mem remember: tell your caller what is worth remembering, "
    "if anything."
)


def test_subagent_start_claude_output_is_byte_identical_to_the_original():
    r = subprocess.run(
        [str(HOOKS / "subagent-start.sh")],
        input="",
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    expected = json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": CLAUDE_SUBAGENT_TEXT,
        }
    })
    assert r.stdout == expected + "\n"


def _bin_with_mem(tmp_path: Path) -> Path:
    b = tmp_path / "pathbin"
    b.mkdir()
    for tool in ("cat", "dirname", "bash"):
        (b / tool).symlink_to(shutil.which(tool) or tool)
    (b / "mem").write_text("#!/bin/sh\n")
    (b / "mem").chmod(0o755)
    return b
