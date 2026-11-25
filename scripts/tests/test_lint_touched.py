"""scripts/lint_touched.py: picks the touched Python files and runs the pinned checks on them."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import lint_touched
import pytest

CHECKS = 3
FIX_CALLS = 5
NO_BASE = 2
SCRIPT = Path(lint_touched.__file__).resolve()


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def write(repo: Path, rel: str, text: str = "x = 1\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo whose `dev` branch holds old.py and gone.py, with `feature` checked out."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "dev")
    write(root, "old.py")
    write(root, "gone.py")
    write(root, ".gitignore", "ignored.py\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    git(root, "checkout", "-q", "-b", "feature")
    return root


def select(root: Path) -> list[str]:
    base = lint_touched.merge_base(root)
    assert base is not None
    return lint_touched.touched_files(root, base)


def test_selects_committed_staged_unstaged_and_untracked(repo: Path) -> None:
    write(repo, "committed.py")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "c")
    write(repo, "staged.py")
    git(repo, "add", "staged.py")
    write(repo, "old.py", "x = 2\n")
    write(repo, "untracked.py")
    assert select(repo) == ["committed.py", "old.py", "staged.py", "untracked.py"]


def test_excludes_deleted_ports_non_python_and_ignored(repo: Path) -> None:
    (repo / "gone.py").unlink()
    write(repo, "ports/gen.py")
    write(repo, "notes.md")
    write(repo, "ignored.py")
    write(repo, "sub/kept.py")
    assert select(repo) == ["sub/kept.py"]


def test_untouched_repo_selects_nothing(repo: Path) -> None:
    assert select(repo) == []


def test_merge_base_is_none_without_dev(tmp_path: Path) -> None:
    root = tmp_path / "nodev"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "commit", "-q", "--allow-empty", "-m", "base")
    assert lint_touched.merge_base(root) is None


def run_script(
    repo: Path, tmp_path: Path, *, uvx_code: int | None, fail_on: str = "", fix: bool = False
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the script from a subdirectory with a shim `uvx` (None: no uvx) and only git on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(shutil.which("git") or "git")
    trace = tmp_path / "trace"
    trace.touch()
    if uvx_code is not None:
        shim = bin_dir / "uvx"
        shim.write_text(
            '#!/bin/sh\necho "$*" >> "$TRACE"\n'
            'if [ -n "$FAIL_ON" ]; then case "$*" in *"$FAIL_ON"*) echo boom; exit 1;; esac; fi\n'
            f"exit {uvx_code}\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
    env = {"PATH": str(bin_dir), "TRACE": str(trace), "FAIL_ON": fail_on}
    (repo / "sub").mkdir(exist_ok=True)
    args = [sys.executable, str(SCRIPT), *(["--fix"] if fix else [])]
    proc = subprocess.run(
        args, env=env, cwd=repo / "sub", capture_output=True, text=True, check=False
    )
    return proc, trace.read_text(encoding="utf-8").splitlines()


def test_all_checks_pass(repo: Path, tmp_path: Path) -> None:
    write(repo, "new.py")
    proc, calls = run_script(repo, tmp_path, uvx_code=0)
    assert proc.returncode == 0
    assert [c.split()[0:2] for c in calls] == [
        [lint_touched.RUFF, "format"],
        [lint_touched.RUFF, "check"],
        ["--with", "pyyaml"],
    ]
    assert "--check" in calls[0]
    assert "--no-fix" in calls[1]
    assert "--warnings" in calls[2]  # a basedpyright warning fails the gate too
    assert all(c.endswith("new.py") for c in calls)
    assert proc.stdout.count(": pass") == CHECKS


@pytest.mark.parametrize("fail_on", ["--check", "--no-fix", lint_touched.BASEDPYRIGHT])
def test_a_failing_tool_fails_the_gate_and_runs_the_rest(
    repo: Path, tmp_path: Path, fail_on: str
) -> None:
    write(repo, "new.py")
    proc, calls = run_script(repo, tmp_path, uvx_code=0, fail_on=fail_on)
    assert proc.returncode == 1
    assert len(calls) == CHECKS
    assert "FAIL" in proc.stdout
    assert "boom" in proc.stdout


def test_no_touched_files_exits_zero_without_running_tools(repo: Path, tmp_path: Path) -> None:
    proc, calls = run_script(repo, tmp_path, uvx_code=0)
    assert proc.returncode == 0
    assert "lint_touched: no touched Python files" in proc.stdout
    assert calls == []


def test_missing_uvx_is_skipped(repo: Path, tmp_path: Path) -> None:
    write(repo, "new.py")
    proc, _ = run_script(repo, tmp_path, uvx_code=None)
    assert proc.returncode == 0
    assert "lint_touched: skipped (uvx not found)" in proc.stdout


def test_missing_base_branch_exits_two(tmp_path: Path) -> None:
    root = tmp_path / "nodev"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "commit", "-q", "--allow-empty", "-m", "base")
    write(root, "new.py")
    proc, _ = run_script(root, tmp_path, uvx_code=0)
    assert proc.returncode == NO_BASE
    assert "no base branch" in proc.stderr


def test_fix_formats_and_fixes_before_checking(repo: Path, tmp_path: Path) -> None:
    write(repo, "new.py")
    proc, calls = run_script(repo, tmp_path, uvx_code=0, fix=True)
    assert proc.returncode == 0
    steps = [c.split()[1:3] for c in calls]
    assert steps[:2] == [["format", "--force-exclude"], ["check", "--fix"]]
    assert "--check" in calls[2]
    assert "--no-fix" in calls[3]
    assert len(calls) == FIX_CALLS


def test_nested_ports_and_odd_names_are_selected(repo: Path) -> None:
    write(repo, "plugins/x/ports/nested.py")
    write(repo, 'odd"name.py')
    write(repo, "tab\tname.py")
    assert select(repo) == sorted(["plugins/x/ports/nested.py", 'odd"name.py', "tab\tname.py"])
