"""Placement rows a model session proposed, checked against what the session was offered.

The answer is data: a row is kept only when every field matches an offered note, part and fingerprint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from integrate import answers
from integrate.rows import row_of

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from integrate.rows import Row


class PartInfo(NamedTuple):
    fingerprint: str
    units: int


class Offered(NamedTuple):
    """What the session saw: note handles, and parts keyed `s:HANDLE#SECTION`."""

    notes: frozenset[str]
    parts: Mapping[str, PartInfo]


def _refusal(row: Row, offered: Offered, placed: set[str]) -> str | None:
    if row.note not in offered.notes:
        return f"{row.note}: not offered"
    part = offered.parts.get(row.target)
    if part is None:
        return f"{row.note}: part not offered"
    if row.fingerprint != part.fingerprint:
        return f"{row.note}: part changed since it was read"
    if row.unit is not None and not 1 <= row.unit <= part.units:
        return f"{row.note}: no such unit {row.unit}"
    if row.note in placed:
        return f"{row.note}: placed twice"
    return None


def placement_rows(lines: Sequence[str], offered: Offered) -> tuple[list[Row], list[str]]:
    """(kept rows, one refusal line per dropped row); `none` and `#` lines produce nothing."""
    kept: list[Row] = []
    refused: list[str] = []
    placed: set[str] = set()
    for line in lines:
        text = line.strip()
        if text == "none" or text.startswith("#"):
            continue
        row = row_of(text)
        if row is None:
            refused.append("malformed row")
            continue
        if reason := _refusal(row, offered, placed):
            refused.append(reason)
            continue
        placed.add(row.note)
        kept.append(row)
    return kept, refused


def offered_of(cand: dict) -> Offered:
    """What a candidate of `mem synthesis integrate --candidates` offered the session: its notes and parts."""
    syn = cand["synthesis"]
    return Offered(
        frozenset(n["handle"] for n in cand["notes"]),
        {
            f"s:{syn}#{p['section']}": PartInfo(p["fingerprint"], len(p["units"]))
            for p in cand["parts"]
        },
    )


def agreed(rows: list[Row], check_answer: str) -> list[Row] | None:
    """The rows the check answer lists too; None when that answer is malformed (it keeps none)."""
    lines = answers.answer_lines(check_answer)
    if lines is None:
        return None
    accepted = {row_of(x) for x in lines if x != "none" and not x.startswith("#")}
    return [row for row in rows if row in accepted]
