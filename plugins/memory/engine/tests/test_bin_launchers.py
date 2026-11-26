"""The `bin/` uv launchers: a bash file that starts `engine/run.py --bin NAME` with uv, or says that uv is missing."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[2] / "bin"
LAUNCHERS = [
    "mem-auto",
    "mem-capture",
    "mem-corroborate",
    "mem-research",
    "mem-settle",
    "mem-synthesize",
]
EXIT_UV_MISSING = 127


@pytest.mark.parametrize("name", LAUNCHERS)
def test_launcher_is_bash_and_names_its_entry(name):
    text = (BIN / name).read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert f'engine/run.py" --bin {name} "$@"' in text


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
    assert "uv is not installed" in done.stderr


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
