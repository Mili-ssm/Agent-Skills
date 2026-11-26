"""A patch of `mem.<name>` reaches only code that looks `name` up in `mem`: tests patch the defining module instead.

ADR 0028: names move out of `mem.py` into `commands/` and `notes/`, and a `monkeypatch.setattr(mem, name, ...)` left
behind would silently patch nothing. This scan fails on a patch of a name `mem.py` does not define itself
(a `def`, a class or an assignment; an imported name does not count)."""

import ast
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
SCANNED = [ENGINE / "tests", ENGINE.parent / "evals"]
MEM = "mem"

# Patches still aimed at an import `mem.py` holds: each A5 task retargets its names to the defining module and
# shrinks this set; it is empty after the last task.
ALLOWED = {"time", "apply_index", "orphan_notes"}

_PATCH_CALLS = {
    "setattr",
    "object",
}  # `monkeypatch.setattr(mem, ...)`, `setattr(mem, ...)`, `patch.object(mem, ...)`


def _defined_in_mem() -> set[str]:
    names: set[str] = set()
    for node in ast.parse((ENGINE / "mem.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _is_mem(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == MEM


def _string(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _call_patch(node: ast.Call) -> str | None:
    """The `mem` name a call patches, or None: `setattr(mem, "n", v)`, `patch.object(mem, "n")`, `patch("mem.n")`."""
    func = node.func
    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    args = node.args
    if called in _PATCH_CALLS and args and _is_mem(args[0]):
        return _string(args[1]) if len(args) > 1 else None
    if called in {"setattr", "patch"} and args and (target := _string(args[0])):
        module, _, name = target.partition(".")
        return name if module == MEM and name and "." not in name else None
    return None


def _assign_patches(node: ast.Assign | ast.AugAssign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [t.attr for t in targets if isinstance(t, ast.Attribute) and _is_mem(t.value)]


def _patched_names(tree: ast.AST) -> list[tuple[int, str]]:
    """`(line, name)` for each patch of a `mem` attribute whose name is a literal."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (name := _call_patch(node)):
            found.append((node.lineno, name))
        elif isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
            found += [(node.lineno, name) for name in _assign_patches(node)]
    return found


def _violations(files: list[Path], defined: set[str]) -> list[str]:
    return sorted(
        f"{path.relative_to(ENGINE.parent)}:{line} patches mem.{name}"
        for path in files
        for line, name in _patched_names(ast.parse(path.read_text(encoding="utf-8")))
        if name not in defined | ALLOWED
    )


def _scanned_files() -> list[Path]:
    return sorted(
        p
        for root in SCANNED
        for p in root.rglob("*.py")
        if p.name != Path(__file__).name and "__pycache__" not in p.parts
    )


def test_no_patch_of_a_name_mem_does_not_define():
    problems = _violations(_scanned_files(), _defined_in_mem())
    assert not problems, "patch the module that defines the name:\n" + "\n".join(problems)


def test_allow_list_names_are_still_patched():
    """An entry nobody patches any more is stale: delete it, so the list only shrinks."""
    patched = {
        name
        for path in _scanned_files()
        for _, name in _patched_names(ast.parse(path.read_text(encoding="utf-8")))
    }
    assert not ALLOWED - patched, f"stale allow-list entries: {sorted(ALLOWED - patched)}"


@pytest.mark.parametrize(
    "source",
    [
        'monkeypatch.setattr(mem, "gone", f)',
        'setattr(mem, "gone", f)',
        'monkeypatch.setattr("mem.gone", f)',
        'mock.patch.object(mem, "gone")',
        'mock.patch("mem.gone")',
        "mem.gone = f",
    ],
)
def test_guard_sees_every_patch_form(source):
    assert [n for _, n in _patched_names(ast.parse(source))] == ["gone"]
