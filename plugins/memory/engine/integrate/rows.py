"""The integrate rows: one line says which note joins which part of a synthesis, and how."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from memories.terms import forbidden_line, secret_in
from syntheses.units import units

if TYPE_CHECKING:
    from collections.abc import Mapping

_FIELDS = 4
_NOTE = re.compile(r"[^\s|]+")
_TARGET = re.compile(r"s:[a-z0-9-]+#[a-z0-9-]+")
_ACTION = re.compile(r"append|unit ([1-9][0-9]*)")
_FINGERPRINT = re.compile(r"[0-9a-f]{10}")


class Row(NamedTuple):
    note: str
    target: str
    action: str
    unit: int | None
    fingerprint: str


def _parse_line(line: str) -> Row | None:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != _FIELDS:
        return None
    note, target, action, fingerprint = parts
    act = _ACTION.fullmatch(action)
    if note.startswith("-"):  # it becomes a command argument; the target always starts with `s:`
        return None
    if not (
        _NOTE.fullmatch(note)
        and _TARGET.fullmatch(target)
        and act
        and _FINGERPRINT.fullmatch(fingerprint)
    ):
        return None
    number = int(act.group(1)) if act.group(1) else None
    return Row(note, target, "unit" if number else "append", number, fingerprint)


def parse_rows(raw: str) -> tuple[list[Row], list[str]]:
    """(rows, messages for the malformed lines); blank lines and `#` lines are ignored."""
    rows: list[Row] = []
    bad: list[str] = []
    for n, line in enumerate(raw.splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        row = _parse_line(text)
        if row is None:
            bad.append(
                f"line {n}: not `NOTE | s:HANDLE#SECTION | append | FINGERPRINT` or `... | unit N | ...`: {text}"
            )
        else:
            rows.append(row)
    return rows, bad


def row_of(line: str) -> Row | None:
    """The row when the line is exactly one well-formed row, else None."""
    rows, bad = parse_rows(line)
    return rows[0] if len(rows) == 1 and not bad else None


def _refusal(text: str, env: Mapping[str, str]) -> str | None:
    if secret_in([text]):
        return "secret in the claim"
    if forbidden_line([text], env) is not None:
        return "forbidden term in the claim"
    if text.endswith(":"):
        return "claim ends with a colon"
    if "[" in text or "]" in text:
        return "claim holds brackets"
    return None


def check_claim(claim: str, env: Mapping[str, str]) -> str | None:
    """Why a claim cannot be joined to a synthesis, or None."""
    text = claim.strip()
    if not text:
        return "claim is empty"
    if reason := _refusal(text, env):
        return reason
    if len(units(text)[0]) != 1:
        return "claim is not one sentence"
    return None
