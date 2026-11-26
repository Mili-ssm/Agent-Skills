"""Characterization of the settle trial's grading (`evals/settle/run_trial.py`): `grade` and `totals_and_verdict`."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

TRIAL = Path(__file__).resolve().parents[3] / "evals" / "settle" / "run_trial.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("settle_run_trial_under_test", TRIAL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(kind, derived):
    return {"type": kind, "base": "b" + derived, "derived": derived, "claim": f"claim {derived}"}


def test_grade_covers_every_branch():
    trial = _load()
    rows = [
        _row("paraphrase", "d1"),  # merge, right direction
        _row("correction", "d2"),  # supersede, wrong direction
        _row("paraphrase", "d3"),  # distinct
        _row("correction", "d4"),  # left
        _row("paraphrase", "d5"),  # never shown
        _row("version", "d6"),  # merge on a version
        _row("unrelated", "d7"),  # nothing from a verdict file
        {"type": "paraphrase", "base": "b", "claim": "c", "error": "boom"},
    ]
    shown = [{"a": "m:d4", "b": "bd4"}, {"a": "x", "b": "y"}]
    log = [
        {"decision": "merge", "older": "bd1", "newer": "d1"},
        {"decision": "supersede", "older": "bd2", "newer": "d2", "reason": "r"},
        {"decision": "distinct", "older": "bd3", "newer": "d3"},
        {"decision": "left", "older": "bd4", "newer": "d4"},
        {"decision": "merge", "older": "bd6", "newer": "d6"},
        {"decision": "merge", "older": "p", "newer": "q"},
        {"decision": "bogus", "older": "z", "newer": "w"},
    ]
    verdicts = [
        {"a": "d7", "b": "bd7", "decision": "nothing", "reason": "same"},
        {"a": "d1", "b": "bd1", "decision": "nothing"},  # the log wins
        {"a": 1, "b": "bd1", "decision": "nothing"},
    ]
    live = {"d1": True, "bd1": False, "d2": False, "bd2": True}
    graded = trial.grade(rows, shown, log, verdicts, live)
    got = [(r["grade"], r["decision"], r["shown"]) for r in graded["rows"]]
    assert got == [
        ("acted", "merge", True),
        ("wrong", "supersede", True),
        ("wrong", "distinct", True),
        ("not acted", "left", True),
        ("retrieval miss", "none", False),
        ("wrong", "merge", True),
        ("correct", "nothing", True),
        ("write failed", "none", False),
    ]
    assert graded["rows"][1]["reason"] == "r"
    assert graded["rows"][6]["reason"] == "same"
    assert graded["rows"][7]["reason"] == "boom"
    assert "derived" not in graded["rows"][7]
    assert graded["unexpected"] == [
        {"pair": ["x", "y"], "decision": "none", "reason": "", "wrong": False},
        {"pair": ["p", "q"], "decision": "merge", "reason": "", "wrong": True},
    ]


def test_totals_and_verdict_counts():
    trial = _load()
    rows = [
        {"type": "paraphrase", "grade": g}
        for g in ("acted", "acted", "acted", "not acted", "wrong")
    ]
    rows += [
        {"type": "unrelated", "grade": "wrong"},
        {"type": "correction", "grade": "retrieval miss"},
    ]
    totals = trial.totals_and_verdict({"rows": rows, "unexpected": [{"wrong": True}]})
    assert (totals["rows"], totals["should_act"], totals["should_act_shown"], totals["acted"]) == (
        7,
        6,
        5,
        3,
    )
    assert (totals["wrong_actions"], totals["wrong_in_rows"], totals["wrong_unexpected"]) == (
        3,
        2,
        1,
    )
    assert totals["verdict"] == "keep the safe subset"
