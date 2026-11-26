"""Placement rows a model session proposed, checked against what the session was offered.

The answer is data: a row is kept only when every field matches an offered note, part and fingerprint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from integrate.rows import parse_rows

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from integrate.rows import Row


class PartInfo(NamedTuple):
    fingerprint: str
    units: int


class Offered(NamedTuple):
    """What the session saw: note handles, and parts keyed `s:HANDLE#SECTION`."""

    notes: Collection[str]
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
        rows, bad = parse_rows(text)
        if bad or len(rows) != 1:
            refused.append("malformed row")
            continue
        row = rows[0]
        if reason := _refusal(row, offered, placed):
            refused.append(reason)
            continue
        placed.add(row.note)
        kept.append(row)
    return kept, refused
