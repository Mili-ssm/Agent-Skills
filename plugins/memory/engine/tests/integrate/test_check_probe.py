"""The check probe (`evals/integrate/check_probe.py`): its fixed row table, its grading on canned answers, and that its
check input is the production input (`check_input` on the same rows)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from entry import integrate as engine
from integrate.rows import row_line

EVALS = Path(__file__).resolve().parents[3] / "evals" / "integrate"
SEED = json.loads((EVALS / "seed.json").read_text(encoding="utf-8"))
SYN = SEED["synthesis"]["slug"]


def _load() -> Any:
    sys.path.insert(0, str(EVALS))
    spec = importlib.util.spec_from_file_location(
        "check_probe_under_test", EVALS / "check_probe.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load()
APPENDS, UNITS, NO_FITS, WRONG_PARTS, WRONG_UNITS = 17, 8, 4, 4, 5
MIN_CONTRADICTIONS = 4 + 2  # four claims of the table and the two seed claims
LABELS = {n["slug"]: n for n in SEED["notes"]}


def _cand() -> dict:
    """The candidate `mem synthesis integrate --candidates` gives for the seed, built from the seed."""
    parts = []
    for part in SEED["synthesis"]["parts"]:
        section = part["section"].lower()
        units = [
            {"n": i, "text": f"{s}[{h}](../{h}.md)"}
            for i, (s, h) in enumerate(part["sentences"], 1)
        ]
        parts.append({"section": section, "fingerprint": f"{len(parts):010x}", "units": units})
    notes = [
        {"handle": n["slug"], "claim": n["claim"], "digest": "0"}
        for n in SEED["notes"]
        if n["label"] not in {"superseded", "disputed"}
    ]
    return {"synthesis": SYN, "notes": notes, "parts": parts}


def _by_group() -> dict[str, list]:
    out: dict[str, list] = {g: [] for g in probe.GROUPS}
    for spec in probe.TABLE:
        out[spec.group].append(spec)
    return out


def test_table_counts() -> None:
    counts = Counter(s.group for s in probe.TABLE)
    assert counts[probe.RIGHT_APPEND] == APPENDS
    assert counts[probe.RIGHT_UNIT] == UNITS
    assert counts[probe.NO_FIT] == NO_FITS
    assert counts[probe.WRONG_PART] == WRONG_PARTS
    assert counts[probe.CONTRADICTION] >= MIN_CONTRADICTIONS
    assert counts[probe.WRONG_UNIT] == WRONG_UNITS


def test_right_rows_follow_the_seed_labels() -> None:
    for spec in _by_group()[probe.RIGHT_APPEND]:
        label = LABELS[spec.note]
        assert label["label"] == "append" and spec.unit is None
        assert label["part"] == f"s:{SYN}#{spec.section}"
    for spec in _by_group()[probe.RIGHT_UNIT]:
        label = LABELS[spec.note]
        assert label["label"] in {"belongs-existing-sentence", "duplicate-of-existing"}
        assert (label["part"], label["sentence"]) == (f"s:{SYN}#{spec.section}", spec.unit)
    appends = {n for n, v in LABELS.items() if v["label"] == "append"}
    assert {s.note for s in _by_group()[probe.RIGHT_APPEND]} == appends


def test_wrong_rows_use_seed_notes_or_injected_claims() -> None:
    assert {s.note for s in _by_group()[probe.NO_FIT]} == {
        n for n, v in LABELS.items() if v["label"] == "on-topic-no-fit"
    }
    for spec in _by_group()[probe.WRONG_PART]:
        assert LABELS[spec.note]["label"] == "append"
        assert LABELS[spec.note]["part"] != f"s:{SYN}#{spec.section}"
    for spec in _by_group()[probe.WRONG_UNIT]:
        part = next(p for p in SEED["synthesis"]["parts"] if p["section"].lower() == spec.section)
        assert LABELS[spec.note]["label"] == "append"
        assert LABELS[spec.note]["part"] == f"s:{SYN}#{spec.section}"
        assert 1 <= spec.unit <= len(part["sentences"])
    for spec in _by_group()[probe.CONTRADICTION]:
        assert spec.note.startswith(probe.CONTRA_PREFIX) and spec.claim and spec.unit is None
    claims = {s.claim for s in _by_group()[probe.CONTRADICTION]}
    assert {LABELS["indexes-speed-all"]["claim"], LABELS["index-everything"]["claim"]} <= claims
    for spec in probe.TABLE:
        assert spec.claim or spec.note in LABELS, spec.note


def test_rows_are_unique_and_sections_exist() -> None:
    cand = _cand()
    lines = [row_line(row) for _, row in probe.rows_of(cand)]
    assert len(lines) == len(set(lines)) == len(probe.TABLE)
    assert {s.section for s in probe.TABLE} <= {p["section"] for p in cand["parts"]}


def test_check_input_is_the_engines_for_the_same_rows() -> None:
    cand = _cand()
    entries, items = probe.probe_items(cand)
    right = [(s, r) for s, r in entries if s.group in probe.RIGHT_GROUPS]
    expected = engine.check_input(cand, [r for _, r in right])
    got = [
        item for (s, _), item in zip(entries, items, strict=True) if s.group in probe.RIGHT_GROUPS
    ]
    assert got == expected
    assert len(items) == len(entries)
    contra = next(i for (s, _), i in zip(entries, items, strict=True) if s.note == "probe-contra-1")
    assert contra["claim"] == probe.CONTRADICTIONS[0][1]
    assert set(contra) == {"row", "claim", "part_text"}


def _answer(entries: list, groups: tuple[str, ...]) -> str:
    return "\n".join(row_line(r) for s, r in entries if s.group in groups) or "none"


def test_grade_clean_and_with_a_wrong_row() -> None:
    entries = probe.rows_of(_cand())
    clean = probe.grade(entries, _answer(entries, probe.RIGHT_GROUPS))
    assert clean["wrong_accepted"] == [] and not clean["failed"] and not clean["malformed"]
    assert clean["groups"][probe.RIGHT_APPEND] == {"accepted": APPENDS, "total": APPENDS}
    bad = probe.grade(entries, _answer(entries, (*probe.RIGHT_GROUPS, probe.CONTRADICTION)))
    assert len(bad["wrong_accepted"]) == len(_by_group()[probe.CONTRADICTION])
    assert {w["group"] for w in bad["wrong_accepted"]} == {probe.CONTRADICTION}


def test_grade_none_malformed_and_failed() -> None:
    entries = probe.rows_of(_cand())
    none = probe.grade(entries, "none")
    assert none["groups"][probe.RIGHT_APPEND]["accepted"] == 0 and not none["malformed"]
    malformed = probe.grade(entries, "I accept all of them")
    assert malformed["malformed"] and malformed["groups"][probe.RIGHT_UNIT]["accepted"] == 0
    failed = probe.grade(entries, None)
    assert failed["failed"] and not failed["malformed"]


def test_totals_and_table_text() -> None:
    entries = probe.rows_of(_cand())
    one = probe.grade(entries, _answer(entries, probe.RIGHT_GROUPS))
    two = probe.grade(entries, _answer(entries, (*probe.RIGHT_GROUPS, probe.WRONG_PART)))
    summed = probe.totals([one, two])
    assert summed["groups"][probe.RIGHT_APPEND] == {"accepted": 2 * APPENDS, "total": 2 * APPENDS}
    assert summed["groups"][probe.WRONG_PART] == {"accepted": WRONG_PARTS, "total": 2 * WRONG_PARTS}
    text = probe.table_text([one, two])
    assert f"wrong rows accepted: {WRONG_PARTS}" in text and "[wrong-part]" in text


@pytest.mark.parametrize("text", ["0", "-1", "abc", "inf"])
def test_budget_must_be_a_finite_amount_above_zero(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        probe._amount(text)
