"""A module run by `exec_module` is registered in `sys.modules` first (kept from the retired 3.11 floor test)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"


def _loaders() -> list[Path]:
    """Every file that may run a module by `exec_module`: the engine tests and the eval harnesses."""
    return [
        *sorted((ENGINE / "tests").rglob("*.py")),
        *sorted((ROOT / "evals").rglob("*.py")),
    ]


REGISTERED = re.compile(r"sys\.modules\[|setitem\(\s*sys\.modules")
RUNS_A_MODULE = re.compile(r"\bexec_module\s*\(")


@pytest.mark.parametrize("script", _loaders(), ids=lambda p: str(p.relative_to(ROOT)))
def test_a_module_loaded_from_a_file_is_registered_before_it_runs(script: Path) -> None:
    """Before Python 3.15, `@dataclass` in a module run by `exec_module` looks the module up in `sys.modules`: an
    unregistered module fails at import on 3.12 to 3.14 while passing on a newer interpreter. A test registers it
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
