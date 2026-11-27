import ast
from pathlib import Path

from memories import records

MEMORY = Path(__file__).resolve().parents[3]
ROOTS = (MEMORY / "engine", MEMORY / "bin", MEMORY / "evals")


def _sources():
    for root in ROOTS:
        for path in sorted(root.rglob("*")):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            if path.suffix == ".py" or (not path.suffix and root.name == "bin"):
                yield path


def _is_records(node):
    return (isinstance(node, ast.Name) and node.id == "records") or (
        isinstance(node, ast.Attribute) and node.attr == "records"
    )


def _names_in(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_records(node.value):
            yield node.attr
        elif isinstance(node, ast.ImportFrom) and node.module == "memories.records":
            yield from (alias.name for alias in node.names)


def _parsed(path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _reached_names():
    reached = {}
    for path in _sources():
        tree = _parsed(path)
        if tree is not None:
            for name in _names_in(tree):
                reached.setdefault(name, path)
    return reached


def test_every_attribute_importers_reach_through_records_is_there():
    reached = _reached_names()
    assert "update" in reached  # the scan finds the usual users
    missing = {name: str(path) for name, path in reached.items() if name not in dir(records)}
    assert not missing
