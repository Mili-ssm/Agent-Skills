"""The memory engine's Codex model table is a copy of what port.py derives from shared/models.toml."""

from __future__ import annotations

import sys
from pathlib import Path

import port

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "memory" / "engine"))
from core import runner


def test_engine_table_equals_port_derivation() -> None:
    want = {
        k: v
        for k, v in port.CODEX_PAIRS.items()
        if k[0] in {"haiku", "sonnet", "opus"} and k[1] in {"low", "medium", "high"}
    }
    assert want == runner.CODEX_MODELS
