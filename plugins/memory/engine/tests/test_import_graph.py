"""The leaf modules stay below mem: notes, index and check import without loading mem."""

import subprocess
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("module", ["notes", "index", "check"])
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
