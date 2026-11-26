"""A patch that reaches every binding of a memory, synthesis or note name, not only the one a test happens to read."""

import sys
from collections.abc import Callable
from types import ModuleType

import pytest


def patch_all(monkeypatch: pytest.MonkeyPatch, name: str, replacement: Callable) -> None:
    """Replace `name` in `memories.records` and in every other `memories.*`, `syntheses.*`, `notes.*` or `commands.*` module that holds it.

    A call through the facade (`records.update` in `mem.py`) looks the name up in `memories.records`; a call inside
    a `memories` or `notes` module (`add_sighting` -> `update`) looks it up in that module, so patching the facade alone misses it.
    """
    holders = [
        module
        for key, module in sys.modules.items()
        if key.startswith(("memories.", "syntheses.", "notes.", "commands."))
        and isinstance(module, ModuleType)
        and hasattr(module, name)
    ]
    assert holders, f"no memories, syntheses, notes or commands module holds {name}"
    for module in holders:
        monkeypatch.setattr(module, name, replacement)
