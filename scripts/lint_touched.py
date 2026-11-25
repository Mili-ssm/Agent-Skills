#!/usr/bin/env python3
"""Gate: every Python file changed against `dev` must be fully clean under Ruff and basedpyright (ADR 0031).

Touched = changed since the merge-base with `origin/dev` (else local `dev`), staged, unstaged or untracked
and not ignored; deleted files and the generated `ports/` are skipped. Untouched files are never checked.
Tools run through `uvx` with pinned versions, configured by the root `ruff.toml` and `pyrightconfig.json`.

    python3 scripts/lint_touched.py          # check
    python3 scripts/lint_touched.py --fix    # apply Ruff's format and safe fixes first, then check

Exit code 0 = clean (or nothing to check, or `uvx` missing: skipped), 1 = a check failed, 2 = no base branch.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RUFF = "ruff@0.17.6"
BASEDPYRIGHT = "basedpyright@1.40.2"
BASE_REFS = ("origin/dev", "dev")
EXCLUDED_PREFIXES = ("ports/",)


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in `root` with unquoted paths."""
    cmd = ["git", "-C", str(root), "-c", "core.quotepath=off", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def repo_root() -> Path:
    """Top level of the repository containing the current directory."""
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(out.stdout.strip())


def merge_base(root: Path) -> str | None:
    """Merge-base of HEAD with the first existing base ref, or None when there is none."""
    for ref in BASE_REFS:
        proc = git(root, "merge-base", "HEAD", ref)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return None


def touched_files(root: Path, base: str) -> list[str]:
    """Sorted repo-relative `.py` paths changed since `base`, staged, unstaged or untracked."""
    changed = git(root, "diff", "--name-only", "-z", base).stdout.split("\0")
    untracked = git(root, "ls-files", "-z", "--others", "--exclude-standard").stdout.split("\0")
    return sorted(
        path
        for path in {*changed, *untracked}
        if path.endswith(".py")
        and not path.startswith(EXCLUDED_PREFIXES)
        and (root / path).is_file()
    )


def run_tool(root: Path, label: str, cmd: list[str], *, report: bool = True) -> bool:
    """Run `cmd` in `root`; print one status line and, on failure, the tool's output."""
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    ok = proc.returncode == 0
    if report:
        print(f"lint_touched: {label}: {'pass' if ok else 'FAIL'}")
        if not ok:
            print((proc.stdout + proc.stderr).rstrip())
    return ok


def fix(root: Path, files: list[str]) -> None:
    """Apply Ruff's formatter and safe autofixes to `files`."""
    run_tool(root, "ruff format", ["uvx", RUFF, "format", "--force-exclude", *files], report=False)
    run_tool(
        root, "ruff fix", ["uvx", RUFF, "check", "--fix", "--force-exclude", *files], report=False
    )


def check(root: Path, files: list[str]) -> bool:
    """Run the three checks (all of them, even after a failure); True when all pass."""
    results = [
        run_tool(
            root, "ruff format", ["uvx", RUFF, "format", "--check", "--force-exclude", *files]
        ),
        run_tool(root, "ruff check", ["uvx", RUFF, "check", "--no-fix", "--force-exclude", *files]),
        run_tool(
            root,
            "basedpyright",
            ["uvx", "--with", "pyyaml", "--with", "pytest", BASEDPYRIGHT, "--warnings", *files],
        ),
    ]
    return all(results)


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--fix", action="store_true", help="apply Ruff format and safe fixes first")
    args = parser.parse_args(argv)
    if shutil.which("uvx") is None:
        print("lint_touched: skipped (uvx not found)")
        return 0
    root = repo_root()
    base = merge_base(root)
    if base is None:
        print(f"lint_touched: no base branch ({' or '.join(BASE_REFS)}) found", file=sys.stderr)
        return 2
    files = touched_files(root, base)
    if not files:
        print("lint_touched: no touched Python files")
        return 0
    if args.fix:
        fix(root, files)
    return 0 if check(root, files) else 1


if __name__ == "__main__":
    sys.exit(main())
