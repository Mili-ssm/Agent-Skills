import json
import os
import subprocess
import sys
from pathlib import Path

import mem
import pytest
from core import safe_io
from test_split_plan import world  # ruff: ignore[unused-import]

TWO = 2
THIRD = 3
EXIT_INJECTED = 77


def run(root, capsys, *args):
    code = mem.main(["--root", str(root), "synthesis", "split", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_candidate_preview_apply_undo(world, tmp_path, capsys):
    root, body, _ = world
    code, out, _ = run(root, capsys, "--candidate", "s:parent#part", "child")
    assert code == 0
    proposal = json.loads(out)["proposal"]
    proposal.update(
        parent_text="General introduction.\n\nSources: [n5](../knowledge/test/n5.md)",
        child_heading="Details",
        child_text=body,
    )
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(proposal))
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    code, out, _ = run(root, capsys, "--preview", str(path))
    assert code == 0 and json.loads(out)["moved"]
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    code, out, _ = run(root, capsys, "--apply", str(path))
    assert code == 0
    group = out.strip()
    assert (root / "syntheses/child.md").exists()
    assert group in run(root, capsys, "--status")[1]
    parent_after_split = (root / "syntheses/parent.md").read_bytes()
    mem.main(["--root", str(root), "restore", "s:parent"])
    capsys.readouterr()
    assert group in run(root, capsys, "--status")[1]
    assert (root / "syntheses/parent.md").read_bytes() == parent_after_split
    assert run(root, capsys, "--undo", group)[0] == 0
    assert not (root / "syntheses/child.md").exists()
    assert run(root, capsys, "--recover")[0] == 0
    assert run(root, capsys, "--recover")[0] == 0


def prepared(world, tmp_path, capsys):
    root, body, _ = world
    proposal = json.loads(run(root, capsys, "--candidate", "s:parent#part", "child")[1])["proposal"]
    proposal.update(
        parent_text="General introduction.\n\nSources: [n5](../knowledge/test/n5.md)",
        child_heading="Details",
        child_text=body,
    )
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(proposal))
    return root, path


def test_readonly_invalid_and_mutually_exclusive(world, tmp_path, capsys):
    root, path = prepared(world, tmp_path, capsys)
    (root / "mem-store.yaml").unlink()
    assert run(root, capsys, "--preview", str(path))[0] == 0
    assert run(root, capsys, "--status")[0] == 0
    for args in (("--apply", str(path)), ("--undo", "a" * 32), ("--recover",)):
        assert run(root, capsys, *args)[0] == TWO
    with pytest.raises(SystemExit):
        run(root, capsys, "--status", "--recover")
    path.write_text('{"part": 3}')
    assert run(root, capsys, "--preview", str(path))[0] == TWO


def test_refuses_undo_after_edit(world, tmp_path, capsys):
    root, path = prepared(world, tmp_path, capsys)
    group = run(root, capsys, "--apply", str(path))[1].strip()
    (root / "syntheses/child.md").write_text("later edit")
    assert run(root, capsys, "--undo", group)[0] == TWO
    assert (root / "syntheses/child.md").read_text() == "later edit"


@pytest.mark.parametrize("operation", ["apply", "undo"])
@pytest.mark.parametrize("failure", ["error", "exit"])
def test_interrupted_write_and_recovery(world, tmp_path, capsys, monkeypatch, operation, failure):  # ruff: ignore[too-many-arguments, too-many-positional-arguments]
    root, path = prepared(world, tmp_path, capsys)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    group = None
    if operation == "undo":
        group = run(root, capsys, "--apply", str(path))[1].strip()
    args = ["--apply", str(path)] if operation == "apply" else ["--undo", group]
    if failure == "error":
        original = safe_io.replace_file
        count = 0

        def fail_second(*a, **kw):
            nonlocal count
            count += 1
            if count == THIRD:
                raise OSError("injected failure")
            return original(*a, **kw)

        monkeypatch.setattr(safe_io, "replace_file", fail_second)
        assert run(root, capsys, *args)[0] == TWO
        monkeypatch.setattr(safe_io, "replace_file", original)
        assert not json.loads(run(root, capsys, "--status")[1])["pending"]
    else:
        code = """import os, sys\nfrom core import safe_io\nimport mem\nold = safe_io.replace_file\nn = 0\ndef replace(*a, **kw):\n global n\n n += 1\n if n == 3: os._exit(77)\n return old(*a, **kw)\nsafe_io.replace_file = replace\nsys.exit(mem.main(sys.argv[1:]))\n"""
        env = {**os.environ, "PYTHONPATH": str(Path(mem.__file__).parent)}
        result = subprocess.run(
            [sys.executable, "-c", code, "--root", str(root), "synthesis", "split", *args],
            env=env,
            check=False,
        )
        assert result.returncode == EXIT_INJECTED
        assert json.loads(run(root, capsys, "--status")[1])["pending"]
        assert run(root, capsys, *args)[0] == TWO
        assert run(root, capsys, "--apply", str(path))[0] == TWO
        assert run(root, capsys, "--undo", group or "a" * 32)[0] == TWO
        assert run(root, capsys, "--recover")[0] == 0
        assert run(root, capsys, "--recover")[0] == 0
    if operation == "apply":
        assert all(p.read_bytes() == data for p, data in before.items())
        assert not (root / "syntheses/child.md").exists()
    else:
        assert (root / "syntheses/child.md").exists()
        assert run(root, capsys, "--undo", group)[0] == 0
        assert not (root / "syntheses/child.md").exists()
