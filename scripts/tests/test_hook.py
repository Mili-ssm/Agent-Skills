"""scripts/hooks/pre-push: runs the checks in order, skips missing tools, fails on any failing check."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "pre-push"


def shim(bin_dir: Path, name: str, exit_code: int) -> None:
    path = bin_dir / name
    path.write_text(f'#!/bin/sh\necho "{name} $*" >> "$TRACE"\nexit {exit_code}\n', encoding="utf-8")
    path.chmod(0o755)


def run_hook(tmp_path: Path, tools: dict[str, int]) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Copy the hook into a throwaway repo layout and run it with only the given shim tools on PATH."""
    hooks = tmp_path / "repo" / "scripts" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy(HOOK, hooks / "pre-push")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, code in tools.items():
        shim(bin_dir, name, code)
    trace = tmp_path / "trace"
    trace.touch()
    env = {"PATH": str(bin_dir), "TRACE": str(trace)}
    proc = subprocess.run(
        ["/bin/sh", str(hooks / "pre-push")], env=env, capture_output=True, text=True, cwd=tmp_path
    )
    return proc, trace.read_text(encoding="utf-8").splitlines()


def test_hook_fails_on_validate_error(tmp_path: Path) -> None:
    proc, calls = run_hook(tmp_path, {"python3": 1, "uv": 0, "claude": 0})
    assert proc.returncode != 0
    assert calls[0] == "python3 scripts/validate.py"
    assert "FAILED validate.py" in proc.stdout


def test_hook_skips_missing_tools(tmp_path: Path) -> None:
    proc, calls = run_hook(tmp_path, {"python3": 0})
    assert proc.returncode == 0
    assert calls == ["python3 scripts/validate.py"]
    assert "pre-push: skipped test suite (uv not found)" in proc.stdout
    assert "pre-push: skipped claude plugin validate (claude not found)" in proc.stdout
