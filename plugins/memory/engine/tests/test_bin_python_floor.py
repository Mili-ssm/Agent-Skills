"""The `bin/` python scripts run under the system `python3` (3.11 floor): what they import must parse as 3.11 and avoid 3.12+ names."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "bin"
ENGINE = ROOT / "engine"
BANNED = ("override", "batched", "TypeAliasType")
# `bin/mem-research` imports research_pipeline -> mem.py (3.12 `type` statements, pyyaml): until the refactor plan task
# "`bin/` holds launchers only" runs every script through uv, it is outside the floor.
EXCLUDED = {"mem-research"}


def _scripts() -> list[Path]:
    return [
        p
        for p in sorted(BIN.iterdir())
        if p.is_file()
        and p.name not in EXCLUDED
        and p.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")
    ]


def _is_import_module(call: ast.Call) -> bool:
    func = call.func
    return (isinstance(func, ast.Attribute) and func.attr == "import_module") or (
        isinstance(func, ast.Name) and func.id == "import_module"
    )


def _names(node: ast.AST) -> set[str]:
    """Module or script names one syntax node refers to."""
    if isinstance(node, ast.Import):
        return {a.name.split(".")[0] for a in node.names}
    if isinstance(node, ast.ImportFrom):
        return {node.module.split(".")[0]} if node.module and not node.level else set()
    if isinstance(node, ast.Call) and _is_import_module(node) and node.args:
        arg = node.args[0]
        return (
            {arg.value} if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else set()
        )
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("mem-")
    ):
        # a bin script loaded by path (`HERE / "mem-synthesize"` through SourceFileLoader)
        return {node.value}
    return set()


def _edges(path: Path) -> set[Path]:
    """Engine modules and sibling bin scripts that `path` imports, loads by `import_module` or loads by path."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set().union(*(_names(node) for node in ast.walk(tree)))
    found: set[Path] = set()
    for name in names:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and (ENGINE / f"{name}.py").is_file():
            found.add(ENGINE / f"{name}.py")
        elif re.fullmatch(r"mem-[a-z]+", name) and (BIN / name).is_file() and name not in EXCLUDED:
            found.add(BIN / name)
    return found - {path}


def _closure(start: Path) -> set[Path]:
    seen = {start}
    todo = [start]
    while todo:
        for dep in _edges(todo.pop()):
            if dep not in seen:
                seen.add(dep)
                todo.append(dep)
    return seen


def _banned_uses(tree: ast.AST) -> set[str]:
    """3.12+ names, by syntax: an import of one, an attribute access (`typing.override`) or a bare `TypeAliasType`."""
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            used.update(a.name for a in node.names if a.name in BANNED)
        elif isinstance(node, ast.Attribute) and node.attr in BANNED:
            used.add(node.attr)
        elif isinstance(node, ast.Name) and node.id == "TypeAliasType":
            used.add(node.id)
    return used


def test_scripts_are_found() -> None:
    assert {p.name for p in _scripts()} >= {
        "mem-auto",
        "mem-capture",
        "mem-corroborate",
        "mem-settle",
        "mem-synthesize",
    }
    assert "mem-synthesize" in {p.name for p in _closure(BIN / "mem-settle")}


@pytest.mark.parametrize("script", _scripts(), ids=lambda p: p.name)
def test_imports_are_python_311_safe(script: Path) -> None:
    for path in sorted(_closure(script)):
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path), feature_version=(3, 11))
        banned = _banned_uses(ast.parse(source))
        assert not banned, f"{script.name} -> {path.name} uses {sorted(banned)}"
