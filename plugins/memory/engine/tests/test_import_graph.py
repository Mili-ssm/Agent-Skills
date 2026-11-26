"""Import direction among engine modules: leaves stay below mem, and no module imports another in a cycle."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("module", ["notes", "index", "check", "session_notices"])
def test_module_imports_without_mem(module):
    code = f"import sys, {module}; assert 'mem' not in sys.modules, sorted(sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, cwd=ENGINE, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_notes_imports_no_other_engine_module():
    code = (
        "import sys; before = set(sys.modules); import notes; "
        "import pathlib; engine = {p.stem for p in pathlib.Path('.').glob('*.py')}; "
        "loaded = (set(sys.modules) - before) & engine - {'notes'}; assert not loaded, loaded"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, cwd=ENGINE, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_check_stays_pure():
    """check.py itself imports no git or subprocess code (a library it loads may use subprocess)."""
    tree = ast.parse((ENGINE / "check.py").read_text(encoding="utf-8"))
    imported = {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    imported |= {
        n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
    }
    assert not {"store_git", "subprocess"} & imported
    code = "import sys, check; assert 'store_git' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, cwd=ENGINE, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_session_notices_does_not_import_mem():
    tree = ast.parse((ENGINE / "session_notices.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "mem" not in imported


MODULES = {path.stem for path in ENGINE.glob("*.py")}


def _trees() -> dict[str, ast.Module]:
    return {
        name: ast.parse((ENGINE / f"{name}.py").read_text(encoding="utf-8"))
        for name in sorted(MODULES)
    }


def _imported_engine_modules(tree: ast.Module, own: str) -> set[str]:
    """Engine modules a tree imports with a static `import` or `from` at any depth, itself excluded."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return (found & MODULES) - {own}


def _cycles(graph: dict[str, set[str]]) -> list[str]:
    """One `a -> b -> a` line per back edge met by a depth-first walk from each module in name order."""
    lines: list[str] = []
    done: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in path:
            lines.append(" -> ".join([*path[path.index(node) :], node]))
            return
        if node in done:
            return
        for target in sorted(graph[node]):
            visit(target, [*path, node])
        done.add(node)

    for name in sorted(graph):
        visit(name, [])
    return lines


def test_engine_modules_import_no_cycle():
    graph = {name: _imported_engine_modules(tree, name) for name, tree in _trees().items()}
    cycles = _cycles(graph)
    assert not cycles, "import cycles among engine modules:\n" + "\n".join(cycles)


def _dynamic_engine_import(node: ast.AST) -> str | None:
    """`import_module("x")` or `__import__("x")` naming an engine module, as its call text."""
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    first = node.args[0]
    if called not in {"import_module", "__import__"} or not isinstance(first, ast.Constant):
        return None
    target = first.value
    if isinstance(target, str) and target.split(".")[0] in MODULES:
        return f"{called}({target!r})"
    return None


def test_engine_modules_import_engine_modules_statically():
    dynamic = [
        f"{name}.py:{getattr(node, 'lineno', 0)} {call}"
        for name, tree in _trees().items()
        for node in ast.walk(tree)
        if (call := _dynamic_engine_import(node))
    ]
    assert not dynamic, "dynamic imports of engine modules:\n" + "\n".join(dynamic)
