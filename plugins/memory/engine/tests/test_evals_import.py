"""Every eval harness imports: a harness that reads a name from `mem` that moved out of it fails here, not in a trial run."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
EVALS = sorted(p for p in (ROOT / "evals").rglob("*.py") if "results" not in p.parts)


@pytest.mark.parametrize("script", EVALS, ids=lambda p: str(p.relative_to(ROOT)))
def test_eval_harness_imports(script: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(ENGINE))
    name = "eval_smoke_" + "_".join(script.relative_to(ROOT).with_suffix("").parts)
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
