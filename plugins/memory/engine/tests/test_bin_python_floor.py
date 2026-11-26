"""The `bin/` python scripts run under the system `python3` (3.11 floor): what they import must parse as 3.11 and avoid 3.12+ names."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "bin"
ENGINE = ROOT / "engine"
BANNED = ("override", "batched", "TypeAliasType")
# `bin/mem-research` imports research.pipeline -> mem.py (3.12 `type` statements, pyyaml): until the refactor plan task
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
        return {a.name for a in node.names} | {a.name.split(".")[0] for a in node.names}
    if isinstance(node, ast.ImportFrom):
        if not node.module or node.level:
            return set()
        # `from synthesize import pipeline` may name a submodule of a package
        return {node.module.split(".")[0], *(f"{node.module}.{a.name}" for a in node.names)}
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
        # a bin script loaded by path (`HERE / "mem-capture"` style, through SourceFileLoader)
        return {node.value}
    return set()


def _edges(path: Path) -> set[Path]:
    """Engine modules and sibling bin scripts that `path` imports, loads by `import_module` or loads by path."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set().union(*(_names(node) for node in ast.walk(tree)))
    found: set[Path] = set()
    for name in names:
        base = ENGINE / name.replace(".", "/")
        module = (
            base / "__init__.py" if base.is_dir() else base.with_suffix(".py")
        )  # a package is its `__init__.py`
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name) and module.is_file():
            found.add(module)
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
    assert ENGINE / "synthesize" / "run.py" in _closure(BIN / "mem-settle")
    assert ENGINE / "core" / "jobs.py" in _closure(BIN / "mem-settle")


@pytest.mark.parametrize("script", _scripts(), ids=lambda p: p.name)
def test_imports_are_python_311_safe(script: Path) -> None:
    for path in sorted(_closure(script)):
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path), feature_version=(3, 11))
        banned = _banned_uses(ast.parse(source))
        assert not banned, f"{script.name} -> {path.name} uses {sorted(banned)}"


def _loaders() -> list[Path]:
    """Every file that may run a module by `exec_module`: the `bin/` scripts, the engine tests and the eval harnesses."""
    return [
        *_scripts(),
        *sorted((ENGINE / "tests").rglob("*.py")),
        *sorted((ROOT / "evals").rglob("*.py")),
    ]


REGISTERED = re.compile(r"sys\.modules\[|setitem\(\s*sys\.modules")
RUNS_A_MODULE = re.compile(r"\bexec_module\s*\(")


@pytest.mark.parametrize("script", _loaders(), ids=lambda p: str(p.relative_to(ROOT)))
def test_a_module_loaded_from_a_file_is_registered_before_it_runs(script: Path) -> None:
    """Before Python 3.15, `@dataclass` in a module run by `exec_module` looks the module up in `sys.modules`: an
    unregistered module fails at import on the 3.11 floor while passing on a newer interpreter. A test registers it
    with `monkeypatch.setitem(sys.modules, ...)` so that teardown removes the entry."""
    if script == Path(__file__).resolve():
        return  # this file spells the call inside its own pattern and probes
    lines = script.read_text(encoding="utf-8").splitlines()
    for at, line in enumerate(lines):
        if RUNS_A_MODULE.search(line):
            before = "\n".join(lines[max(0, at - 5) : at])
            assert REGISTERED.search(before), (
                f"{script.name}:{at + 1} runs a module not in sys.modules"
            )


@pytest.mark.parametrize(
    ("line", "runs"),
    [
        ("    spec.loader.exec_module(m)", True),
        ("if ok: spec.loader.exec_module(m)", True),
        ("return loader.exec_module(m)", True),
        ("loader.exec_module (m)", True),
        ('mods["x"].exec_module(m)', True),
        ("# exec_module is mentioned here", False),
    ],
)
def test_the_matcher_finds_every_form_of_exec_module_call(line: str, runs: bool) -> None:
    assert bool(RUNS_A_MODULE.search(line)) is runs
