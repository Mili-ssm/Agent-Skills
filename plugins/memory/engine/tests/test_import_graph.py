"""Import direction among engine modules: leaves stay below mem, and no module imports another in a cycle."""

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
PACKAGE = "synthesize"


def _module_name(path: Path) -> str:
    """Dotted name of an engine file: `a/b.py` is `a.b`, a package's `__init__.py` is the package."""
    parts = list(path.relative_to(ENGINE).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


ENGINE_FILES = sorted(p for p in ENGINE.rglob("*.py") if "tests" not in p.relative_to(ENGINE).parts)
MODULES = {_module_name(path) for path in ENGINE_FILES}
# Feature packages: the directories of the engine that hold an `__init__.py`.
PACKAGES = {path.parent.name for path in ENGINE_FILES if path.name == "__init__.py"}


# The check family: pure rules and queries over a notes folder.
PURE_CHECK_MODULES = ["notes.check", "notes.fields", "notes.links", "notes.due", "notes.search"]
NOTE_MODULES = ["notes.note", "notes.index", "notes.split_candidates", *PURE_CHECK_MODULES]
SYNTHESES_MODULES = [
    "syntheses.document",
    "syntheses.units",
    "syntheses.edit",
    "syntheses.project",
    "syntheses.split_conservation",
]


def test_modules_cover_every_engine_file():
    """One module name per file: a file whose name collides with another would hide from every rule below."""
    assert len(MODULES) == len(ENGINE_FILES), sorted(MODULES)


def _source(name: str) -> Path:
    """The file of a module name: `a.b` is `a/b.py`, a package is its `__init__.py`."""
    path = ENGINE / name.replace(".", "/")
    return path / "__init__.py" if path.is_dir() else path.with_suffix(".py")


@pytest.mark.parametrize(
    "module", [*NOTE_MODULES, *SYNTHESES_MODULES, "session.notices", "commands.split_plan"]
)
def test_module_imports_without_mem(module):
    code = f"import sys, {module}; assert 'mem' not in sys.modules, sorted(sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, cwd=ENGINE, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_note_module_imports_only_core_yaml_load():
    code = (
        "import sys; before = set(sys.modules); from notes import note; "
        f"engine = {sorted(MODULES)!r}; "
        "loaded = (set(sys.modules) - before) & set(engine) - {'notes', 'notes.note', 'core', 'core.yaml_load'}; assert not loaded, loaded"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, cwd=ENGINE, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", PURE_CHECK_MODULES)
def test_check_stays_pure(module):
    """The check family imports no git or subprocess code (a library it loads may use subprocess)."""
    tree = ast.parse(_source(module).read_text(encoding="utf-8"))
    imported = {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    imported |= {
        n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
    }
    imported |= {
        f"{n.module}.{a.name}"
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module
        for a in n.names
    }
    assert not {"store_git", "core.store_git", "subprocess"} & imported
    code = f"import sys, {module}; assert 'core.store_git' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, cwd=ENGINE, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_session_notices_does_not_import_mem():
    tree = ast.parse((ENGINE / "session" / "notices.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "mem" not in imported


def _trees() -> dict[str, ast.Module]:
    return {name: ast.parse(_source(name).read_text(encoding="utf-8")) for name in sorted(MODULES)}


def _imported_engine_modules(tree: ast.Module, own: str) -> set[str]:
    """Engine modules a tree imports with a static `import` or `from` at any depth, itself excluded."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.update({alias.name, alias.name.split(".")[0]})
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.update({node.module.split(".")[0], node.module})
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
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


def _dynamic_import(node: ast.AST) -> str | None:
    """Text of an `importlib` import or of a call named `import_module` or `__import__`, any argument.

    Banning `importlib` itself also catches an aliased `import_module`.
    """
    if isinstance(node, ast.Import) and any(
        a.name.split(".")[0] == "importlib" for a in node.names
    ):
        return "import importlib"
    if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "importlib":
        return f"from {node.module} import ..."
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return f"{called}(...)" if called in {"import_module", "__import__"} else None


def test_engine_modules_use_no_dynamic_import():
    """A dynamic import hides an edge from the graph above, so no engine module may make one."""
    dynamic = [
        f"{name}.py:{getattr(node, 'lineno', 0)} {call}"
        for name, tree in _trees().items()
        for node in ast.walk(tree)
        if (call := _dynamic_import(node))
    ]
    assert not dynamic, "dynamic imports in engine modules:\n" + "\n".join(dynamic)


MEMORY_AND_NOTE_MODULES = (
    tuple(f"memories.{name}" for name in ("records", "rules", "fingerprints"))
    + tuple(f"notes.{name}" for name in ("index", "note", "check"))
    + tuple(SYNTHESES_MODULES)
)


def test_memory_and_note_modules_never_import_synthesize():
    """The store sits below the synthesis feature: no store module reaches `synthesize`, directly or through others."""
    graph = {name: _imported_engine_modules(tree, name) for name, tree in _trees().items()}
    reached: dict[str, list[str]] = {}
    for store in MEMORY_AND_NOTE_MODULES:
        seen: set[str] = set()
        todo = [store]
        while todo:
            for dep in graph[todo.pop()] - seen:
                seen.add(dep)
                todo.append(dep)
        if hit := sorted(m for m in seen if m.split(".")[0] == PACKAGE):
            reached[store] = hit
    assert not reached, f"store modules reaching the synthesize package: {reached}"


# Every cross-package edge allowed in the engine, as (importer, imported), frozen at the base of backlog A14
# (docs/superpowers/plans/done/2026-11-26-memory-engine-packages.md). Each package task adds its package to the
# engine; an edge not listed here is new and fails. The list only shrinks.
FROZEN_EDGES = {
    ("corroborate", "capture"),
    ("corroborate", "digest"),
    ("corroborate", "synthesize"),
    ("research", "synthesize"),
}
PLANNED_PACKAGES = {
    "corroborate", "research", "capture", "settle", "digest", "session", "core", "memories", "syntheses", "notes", "synthesize", "entry", "commands", "integrate",
}  # fmt: skip


def test_packages_are_planned_and_edges_frozen():
    """Packages import each other only along FROZEN_EDGES (any package may import the base layers `core`, `memories`, `syntheses` and `notes`; `entry` and `commands`, the top layers, may import any package); `core` imports no other package."""
    assert PACKAGES <= PLANNED_PACKAGES, sorted(PACKAGES - PLANNED_PACKAGES)
    graph = {name: _imported_engine_modules(tree, name) for name, tree in _trees().items()}
    new_edges = sorted(
        f"{name} -> {dep}"
        for name, deps in graph.items()
        if (own := name.split(".")[0]) in PACKAGES and own not in TOP_LAYERS
        for dep in deps
        if (target := dep.split(".")[0]) in PACKAGES
        # itself and the base layers (`core`, `memories`, `syntheses`, `notes`) are not cross-package edges
        and target not in {own, "core", "memories", "syntheses", "notes"}
        and (own, target) not in FROZEN_EDGES
    )
    assert not new_edges, f"cross-package edges outside the frozen list: {new_edges}"


# Engine modules a package may import besides its own and stdlib: its low-level dependencies and the
# frozen edges to other features. `entry` is the top layer: it imports any package, and only `run` imports it. `core`, `memories`, `syntheses` and `notes` are base layers that any package may
# import: `core` imports only itself and the standard library, `memories` only those and `core`, `syntheses` those
# and `memories`, `notes` those and `syntheses`; `memories` never imports `syntheses` or `notes`, and `syntheses`
# never imports `notes` (the owner ruling that split the old `store`, ADR 0034).
ENTRY_PACKAGE = "entry"
COMMANDS_PACKAGE = (
    "commands"  # the `mem` command handlers (A5, ADR 0028): a top layer, imported only by `mem`
)
TOP_LAYERS = {ENTRY_PACKAGE, COMMANDS_PACKAGE}
PACKAGE_DEPENDENCIES = {
    "core": set(),
    "memories": {"core"},
    "syntheses": {"core", "memories"},
    "notes": {"core", "memories", "syntheses"},
    "corroborate": {"core", "memories", "capture", "digest", "synthesize"},
    "capture": {"core", "memories"},
    "settle": {"core", "memories"},
    "integrate": {"core", "memories", "syntheses", "notes"},
    "digest": {"memories"},
    "session": {"core", "notes"},
    "research": {"core", "memories", "notes", "synthesize"},
    "entry": {"core", "memories", "syntheses", "notes", "corroborate", "research", "capture", "settle", "digest", "session", "synthesize", "integrate"},
    "commands": {"core", "memories", "syntheses", "notes", "corroborate", "research", "capture", "settle", "digest", "session", "synthesize", "integrate"},
}  # fmt: skip
# Engine modules that may import a package (tests, `bin/` and the eval harnesses are outside the engine).
PACKAGE_IMPORTERS = {
    "corroborate": {"mem", "commands"},
    "research": {"mem", "commands"},
    "capture": {"mem", "corroborate", "commands"},
    "settle": {"mem", "commands"},
    "integrate": {"mem", "commands"},
    "digest": {"mem", "corroborate", "commands"},
    "session": {"mem", "commands"},
    "entry": {"run"},
    "commands": {"mem"},
}


def test_package_imports_only_its_dependencies():
    graph = {name: _imported_engine_modules(tree, name) for name, tree in _trees().items()}
    for package, allowed in PACKAGE_DEPENDENCIES.items():
        extra = {
            f"{name} -> {dep}"
            for name, deps in graph.items()
            if name.split(".")[0] == package
            for dep in deps
            if dep.split(".")[0] not in allowed | {package}
        }
        assert not extra, f"{package} imports outside its dependencies: {sorted(extra)}"


def test_package_is_imported_only_by_its_importers():
    graph = {name: _imported_engine_modules(tree, name) for name, tree in _trees().items()}
    for package, allowed in PACKAGE_IMPORTERS.items():
        exempt = (
            set() if package == COMMANDS_PACKAGE else {ENTRY_PACKAGE}
        )  # `entry` never imports `commands`
        extra = sorted(
            name
            for name, deps in graph.items()
            if name.split(".")[0] not in allowed | {package} | exempt
            and any(dep.split(".")[0] == package for dep in deps)
        )
        assert not extra, f"modules importing {package} that may not: {extra}"


# Root modules: the entry points `mem` and `run`. No package may import them: a package that imports an entry
# point couples a feature to the launcher.
ENTRY_MODULES = {"mem", "run"}


def test_no_package_imports_the_entry_modules():
    graph = {name: _imported_engine_modules(tree, name) for name, tree in _trees().items()}
    extra = sorted(
        f"{name} -> {dep}"
        for name, deps in graph.items()
        if name.split(".")[0] in PACKAGES
        for dep in deps & ENTRY_MODULES
    )
    assert not extra, f"packages importing `mem` or `run`: {extra}"


def test_engine_uses_no_relative_imports():
    """A relative import (`from . import x`) would hide an edge from every rule above, which read absolute names."""
    relative = sorted(
        name
        for name, tree in _trees().items()
        if any(isinstance(node, ast.ImportFrom) and node.level > 0 for node in ast.walk(tree))
    )
    assert not relative, f"relative imports in: {relative}"


def test_store_modules_import_the_defining_module_not_the_records_facade():
    """`memories/records.py` re-exports for the importers outside `memories`; inside it every module names the module that defines what it uses."""
    graph = {name: _imported_engine_modules(tree, name) for name, tree in _trees().items()}
    extra = sorted(
        name
        for name, deps in graph.items()
        if name.startswith("memories.")
        and name != "memories.records"
        and "memories.records" in deps
    )
    assert not extra, f"store modules importing the records facade: {extra}"


def test_package_docstring_maps_every_module():
    """An agent reads a package's `__init__.py` docstring as its module map: one `` `name`: role`` line per module, none for a missing one."""
    problems = []
    for init in sorted(ENGINE.glob("*/__init__.py")):
        doc = ast.get_docstring(ast.parse(init.read_text(encoding="utf-8"))) or ""
        listed = set(re.findall(r"^`(\w+)`: \S", doc, re.MULTILINE))
        files = {p.stem for p in init.parent.glob("*.py")} - {"__init__"}
        problems += [f"{init.parent.name}: no entry for {name}" for name in sorted(files - listed)]
        problems += [
            f"{init.parent.name}: entry for missing {name}" for name in sorted(listed - files)
        ]
    assert not problems, problems
