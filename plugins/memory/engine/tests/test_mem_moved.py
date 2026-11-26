"""`mem` keeps serving the names that moved out of it: callers and tests read them as `mem.<name>`."""

import ast
from pathlib import Path

import mem
import pytest

ENGINE = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("name", sorted(mem._MOVED))
def test_moved_name_resolves_through_mem(name):
    assert getattr(mem, name) is not None


def _defined_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


@pytest.mark.parametrize("name", sorted(mem._MOVED))
def test_moved_name_maps_to_the_module_that_defines_it(name):
    """`_MOVED` names one defining module per name: a name a module only re-exports would hide a second definition."""
    module = mem._MOVED[name]
    path = ENGINE / (module.replace(".", "/") + ".py")
    assert name in _defined_names(path.read_text(encoding="utf-8"))
    assert module in mem._MOVED_MODULES
