"""The `bin/` uv launchers: a bash file that starts `engine/run.py --bin NAME` with uv, or says that uv is missing."""

import datetime
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from settle import state as settle_state

ENGINE = Path(__file__).resolve().parents[1]
BIN = ENGINE.parent / "bin"
RUN = ENGINE / "run.py"
LAUNCHERS = [
    "mem-auto",
    "mem-capture",
    "mem-corroborate",
    "mem-research",
    "mem-settle",
    "mem-synthesize",
]
EXIT_UV_MISSING = 127


def _run_py_names() -> set[str]:
    """The `--bin` names `engine/run.py` dispatches."""
    return set(re.findall(r'name == "([^"]+)"', RUN.read_text(encoding="utf-8")))


def _bin_files() -> list[Path]:
    return sorted(p for p in BIN.iterdir() if p.is_file())


def test_every_bin_file_is_a_bash_launcher_of_its_own_name():
    for path in _bin_files():
        text = path.read_text(encoding="utf-8")
        assert text.startswith("#!/usr/bin/env bash\n"), path.name
        assert os.access(path, os.X_OK), path.name
        if path.name == "mem":
            assert 'engine/run.py" "$@"' in text and "--bin" not in text
        else:
            assert f'engine/run.py" --bin {path.name} "$@"' in text, path.name


def test_every_bin_name_in_run_py_has_a_launcher_and_vice_versa():
    launchers = {p.name for p in _bin_files()} - {"mem"}
    assert _run_py_names() == launchers


def test_the_settle_write_path_starts_the_launcher_without_an_interpreter(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(settle_state.subprocess, "Popen", lambda cmd, **_: started.append(cmd))
    monkeypatch.setattr(settle_state.settle_verdicts, "due", lambda *_: object())
    environ = {settle_state.ENV_FLAG: "1"}
    assert settle_state.maybe_start(tmp_path, None, environ, 0.0, datetime.date(2026, 1, 1))
    assert started[0][0] == str(BIN / "mem-settle")
    assert os.access(started[0][0], os.X_OK)


@pytest.mark.parametrize("name", LAUNCHERS)
def test_launcher_without_uv_exits_127_with_a_message(name, tmp_path):
    shim = tmp_path / "shim"
    shim.mkdir()
    dirname = shutil.which("dirname")
    assert dirname
    (shim / "dirname").symlink_to(dirname)
    done = subprocess.run(
        ["/bin/bash", str(BIN / name), "--help"],
        env={"PATH": str(shim)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stdout) == (EXIT_UV_MISSING, "")
    assert done.stderr.startswith(f"{name}: uv is not installed (https://docs.astral.sh/uv/)")


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
@pytest.mark.parametrize("name", LAUNCHERS)
def test_launcher_runs_help_through_uv(name):
    done = subprocess.run(
        [str(BIN / name), "--help"],
        env=os.environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert f"usage: {name}" in done.stdout


def test_run_rejects_an_unknown_bin_name():
    run = BIN.parent / "engine" / "run.py"
    done = subprocess.run(
        [shutil.which("python3") or "python3", str(run), "--bin", "mem-nope"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stdout) == (2, "")
    assert "unknown --bin name" in done.stderr
