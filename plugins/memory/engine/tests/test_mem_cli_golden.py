"""Golden `mem` command line: every `--help` (stdout) and the stderr and exit code of every usage error.

Pinned at plan base (A5, Task 1) before `build_parser().error` became `UsageError` and the handlers moved to
`commands/`: the stored text stays unchanged across the moves. Regenerate only on purpose:
`UPDATE_GOLDEN=1 pytest tests/test_mem_cli_golden.py`, then read the diff."""

import argparse
import json
import os
import shutil
from pathlib import Path

import mem
import pytest

GOLDEN = Path(__file__).resolve().parent / "golden" / "mem_cli.json"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "valid"

# One invocation per call site that ends in the top parser's error, 12 sites in all (the plan counted ten).
EXIT_USAGE = 2  # argparse's exit code for a usage error
USAGE_ERROR_SITES = 12
USAGE_ERRORS: dict[str, list[str]] = {
    "show --ranges": ["show", "x.md", "--ranges"],
    "memory edit no flags": ["memory", "edit", "m:abc"],
    "terms add --kind": ["terms", "add", "foo", "--kind", "decision"],
    "synthesis add one call": [
        "synthesis",
        "add",
        "s:abc",
        "--section",
        "S",
        "--body-file",
        "b.md",
        "--note-slug",
        "a",
    ],
    "note edit no option": ["note", "edit", "x.md"],
    "note edit --section alone": ["note", "edit", "x.md", "--section", "S"],
    "note dispute --clear with fact": ["note", "dispute", "x.md", "--clear", "--fact", "f"],
    "note confirm no fact": ["note", "confirm", "x.md"],
    "stats PATH": ["stats", "foo"],
    "search no words": ["search", "!!!"],
    "search --links --offset": ["search", "abc", "--links", "--offset", "2"],
    "passages no words": ["passages", ".", "!!!"],
}


def _subcommand_paths(
    parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()
) -> list[tuple[str, ...]]:
    """The command path of every subparser, depth first: `("note", "edit")`, `("new", "knowledge")`."""
    paths: list[tuple[str, ...]] = []
    for action in parser._actions:  # argparse has no public listing of subparsers
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                paths.append((*prefix, name))
                paths += _subcommand_paths(sub, (*prefix, name))
    return paths


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    code: object = None
    try:
        code = mem.main(argv)
    except SystemExit as exit_:
        code = exit_.code
    out = capsys.readouterr()
    return {"code": code, "stdout": out.out, "stderr": out.err}


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "hub"
    shutil.copytree(FIXTURE, root)
    (root / "mem-store.yaml").write_text("format: 1\n", encoding="utf-8")
    monkeypatch.setenv("MEM_STORE", str(root))
    monkeypatch.setenv("COLUMNS", "80")  # argparse wraps help at the terminal width
    return root


def _collect(capsys: pytest.CaptureFixture[str]) -> dict[str, dict[str, object]]:
    golden: dict[str, dict[str, object]] = {}
    for path in [(), *_subcommand_paths(mem.build_parser())]:
        golden["help " + " ".join(path)] = _run([*path, "--help"], capsys)
    for name, argv in USAGE_ERRORS.items():
        golden["error " + name] = _run(argv, capsys)
    return golden


def test_cli_matches_golden(store, capsys):
    actual = _collect(capsys)
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sorted(actual) == sorted(expected)
    for key in sorted(expected):
        assert actual[key] == expected[key], key


def test_golden_covers_help_and_errors(store, capsys):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    helps = [k for k in golden if k.startswith("help ")]
    errors = [k for k in golden if k.startswith("error ")]
    assert len(helps) == len(_subcommand_paths(mem.build_parser())) + 1
    assert len(errors) == USAGE_ERROR_SITES
    assert all(golden[k]["code"] == 0 for k in helps)
    assert all(
        golden[k]["code"] == EXIT_USAGE and "mem: error:" in golden[k]["stderr"] for k in errors
    )
