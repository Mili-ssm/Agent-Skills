"""The leaf modules stay below mem: notes, index and check import without loading mem."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("module", ["notes", "index", "check", "session_notices"])
def test_module_imports_without_mem(module):
    code = f"import sys, {module}; assert 'mem' not in sys.modules, sorted(sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], cwd=ENGINE, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_notes_imports_no_other_engine_module():
    code = ("import sys; before = set(sys.modules); import notes; "
            "import pathlib; engine = {p.stem for p in pathlib.Path('.').glob('*.py')}; "
            "loaded = (set(sys.modules) - before) & engine - {'notes'}; assert not loaded, loaded")
    result = subprocess.run([sys.executable, "-c", code], cwd=ENGINE, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_check_stays_pure():
    """check.py itself imports no git or subprocess code (a library it loads may use subprocess)."""
    tree = ast.parse((ENGINE / "check.py").read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not {"store_git", "subprocess"} & imported
    code = "import sys, check; assert 'store_git' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", code], cwd=ENGINE, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_session_notices_does_not_import_mem():
    tree = ast.parse((ENGINE / "session_notices.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "mem" not in imported
