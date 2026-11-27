"""Placement rows a model session proposed, checked against what the session was offered.

The answer is data: a row is kept only when every field matches an offered note, part and fingerprint.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

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


_LABEL = re.compile(r"\s*row:\s*", re.IGNORECASE)


class _Scan(NamedTuple):
    accepted: list[Row]
    none: bool  # a `none` line came
    prose: bool  # a line that is not row-shaped (no ` | `): a header or a sentence
    ignored: list[str]


def _scan(rows: list[Row], check_answer: str) -> _Scan:
    """The check answer read line by line: a row-shaped stray line (a cut row, a row not proposed) is ignored; a
    prose line is recorded, because a header such as "Rejected:" may sit above rows the session refused."""
    accepted: list[Row] = []
    none = prose = False
    ignored: list[str] = []
    for raw in check_answer.splitlines():
        text = raw.strip()
        if not text or text.startswith(("```", "#")):
            continue
        if text == "none":
            none = True
            continue
        row = row_of(_LABEL.sub("", text, count=1) if _LABEL.match(text) else text)
        if row is not None and row in rows:
            accepted.append(row)
        else:
            ignored.append(text)
            prose = prose or " | " not in text
    return _Scan(accepted, none, prose, ignored)


def agreed(rows: list[Row], check_answer: str) -> list[Row] | None:
    """The rows the check answer lists too; stray lines (a `row:` label is stripped first) are ignored, so only a
    row that was proposed can be kept. None when the answer decided nothing (no row and no `none`), `none` comes
    with a row, or a line is prose rather than a row."""
    scan = _scan(rows, check_answer)
    if scan.prose or (scan.none and scan.accepted) or not (scan.none or scan.accepted):
        return None
    return [row for row in rows if row in scan.accepted]


def ignored_lines(rows: list[Row], check_answer: str) -> list[str]:
    """The lines of the check answer `agreed` ignored, for the log."""
    return _scan(rows, check_answer).ignored
