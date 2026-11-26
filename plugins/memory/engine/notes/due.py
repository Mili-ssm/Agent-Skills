"""Requirement rows and the due queries: `rule_requirements` and the re-test, re-read and review lists. Pure."""

from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING

from notes import note as notes_mod
from notes.fields import _DATE, Problem
from notes.note import FrontmatterError, descendants, discover_notes, load_topics, root_of

if TYPE_CHECKING:
    from pathlib import Path

    from notes.note import Note


_REQUIREMENTS = "docs/requirements.md"
_INTENT_ID = re.compile(r"I-[0-9]+")
_CONCRETE_ID = re.compile(r"C-[0-9]+")
# Cells of a concrete requirement row: ID, Requirement, Serves, Rests on, Revisit when, Review by.
REQUIREMENT_CELLS = 6


def _backtick_run(line: str, i: int) -> str:
    """The run of backticks that starts at `line[i]`."""
    return "`" * (len(line) - i - len(line[i:].lstrip("`")))


def _split_cells(line: str) -> list[str]:
    """Cells of a table row, split on '|' outside inline code spans (a literal '|' in a cell is unsupported)."""
    line = line.strip().removeprefix("|").removesuffix("|")
    cells, start, i = [], 0, 0
    while i < len(line):
        if line[i] == "`":
            run = _backtick_run(line, i)
            close = line.find(run, i + len(run))
            i = close + len(run) if close != -1 else i + len(run)
        elif line[i] == "|":
            cells.append(line[start:i].strip())
            start = i = i + 1
        else:
            i += 1
    cells.append(line[start:].strip())
    return cells


def _requirement_rows(root: Path) -> list[tuple[int, list[str]]] | None:
    """(line, cells) of the table rows whose first cell is an I-n or C-n id; None when the file is absent."""
    path = root / _REQUIREMENTS
    if not path.is_file():
        return None
    try:
        text = notes_mod._read_text(path)
    except FrontmatterError:
        return None
    rows = []
    for number, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith("|"):
            cells = _split_cells(line)
            if _INTENT_ID.fullmatch(cells[0]) or _CONCRETE_ID.fullmatch(cells[0]):
                rows.append((number, cells))
    return rows


def _iso_date(value: str) -> datetime.date | None:
    if not _DATE.fullmatch(value):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def rule_requirements(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 12: docs/requirements.md rows are well formed (checked only when the file exists)."""
    rows = _requirement_rows(root)
    if not rows:
        return []
    problems = []
    seen: set[str] = set()
    intents = {cells[0] for _, cells in rows if _INTENT_ID.fullmatch(cells[0])}
    for number, cells in rows:
        ident = cells[0]
        if ident in seen:
            problems.append(
                Problem(
                    _REQUIREMENTS,
                    number,
                    f"duplicate id {ident}: give each requirement a unique id",
                )
            )
        seen.add(ident)
        if _CONCRETE_ID.fullmatch(ident):
            problems += _concrete_row_problems(number, cells, intents)
    return problems


def _concrete_row_problems(number: int, cells: list[str], intents: set[str]) -> list[Problem]:
    ident = cells[0]
    if len(cells) != REQUIREMENT_CELLS:
        return [
            Problem(
                _REQUIREMENTS,
                number,
                f"{ident} has {len(cells)} cells: use exactly {REQUIREMENT_CELLS} "
                "(ID, Requirement, Serves, Rests on, Revisit when, Review by)",
            )
        ]
    problems = []
    if _iso_date(cells[5]) is None:
        problems.append(
            Problem(
                _REQUIREMENTS,
                number,
                f"{ident} has an invalid 'Review by' date "
                f"'{cells[5]}': use a real date as YYYY-MM-DD",
            )
        )
    served = [c.strip() for c in cells[2].split(",")]
    unknown = [c for c in served if c not in intents]
    if unknown:
        problems.append(
            Problem(
                _REQUIREMENTS,
                number,
                f"{ident} serves unknown intent "
                f"{', '.join(repr(u) for u in unknown)}: list existing I-ids, comma-separated",
            )
        )
    return problems


# Model-specific advice ages; see docs/requirements.md C-13.
MODEL_SPECIFIC_ROOT = "llm"
# Days after `updated` before such a note is listed for re-testing; see docs/requirements.md C-13.
RETEST_DAYS = 365
# Days after `added` (the date the source was last read) before a vendor web page is listed for re-reading;
# see docs/requirements.md C-15.
REREAD_DAYS = 182


def _retest_lines(notes: list[Note], topics: dict, today: datetime.date) -> list[str]:
    if MODEL_SPECIFIC_ROOT not in topics:
        return []
    scope = descendants(topics, MODEL_SPECIFIC_ROOT)
    # Only notes homed in llm's domain: a math note tagged llm-evaluation states statistics, not model behaviour.
    home = f"knowledge/{root_of(topics, MODEL_SPECIFIC_ROOT)}/"
    lines = []
    for note in notes:
        if (
            note.type != "knowledge"
            or note.error is not None
            or not isinstance(note.meta, dict)
            or not note.rel.startswith(home)
        ):
            continue
        listed = note.meta.get("topics")
        updated = (
            _iso_date(note.meta["updated"]) if isinstance(note.meta.get("updated"), str) else None
        )
        if (
            updated is None
            or not isinstance(listed, list)
            or not scope.intersection(t for t in listed if isinstance(t, str))
        ):
            continue
        if (today - updated).days > RETEST_DAYS:
            lines.append(
                f"{note.rel}:1: re-test: updated {updated}; "
                "advice that depends on model behaviour ages (spec 5.4)"
            )
    return lines


def _reread_lines(notes: list[Note], topics: dict, today: datetime.date) -> list[str]:
    if MODEL_SPECIFIC_ROOT not in topics:
        return []
    scope = descendants(topics, MODEL_SPECIFIC_ROOT)
    home = f"literature/{root_of(topics, MODEL_SPECIFIC_ROOT)}/"
    lines = []
    for note in notes:
        if (
            note.type != "literature"
            or note.error is not None
            or not isinstance(note.meta, dict)
            or not note.rel.startswith(home)
            or note.meta.get("kind") != "web"
        ):
            continue
        listed = note.meta.get("topics")
        added = _iso_date(note.meta["added"]) if isinstance(note.meta.get("added"), str) else None
        if (
            added is None
            or not isinstance(listed, list)
            or not scope.intersection(t for t in listed if isinstance(t, str))
        ):
            continue
        if (today - added).days > REREAD_DAYS:
            lines.append(
                f"{note.rel}:1: re-read: added {added}; vendor documentation changes (spec 5.3)"
            )
    return lines


def due_retests(root: Path, today: datetime.date) -> list[str]:
    """Lines for knowledge notes on llm topics not updated within RETEST_DAYS, sorted by path."""
    try:
        topics = load_topics(root)
    except FrontmatterError:  # `check` reports an unusable topics.yaml
        return []
    return (
        _retest_lines(discover_notes(root), topics, today) if MODEL_SPECIFIC_ROOT in topics else []
    )


def due_rereads(root: Path, today: datetime.date) -> list[str]:
    """Lines for llm web literature notes whose `added` is over REREAD_DAYS old, sorted by path."""
    try:
        topics = load_topics(root)
    except FrontmatterError:  # `check` reports an unusable topics.yaml
        return []
    return (
        _reread_lines(discover_notes(root), topics, today) if MODEL_SPECIFIC_ROOT in topics else []
    )


def due_counts(root: Path, today: datetime.date) -> tuple[int, int]:
    """(notes to re-test, notes to re-read) from one scan; the same notes the two line lists above report."""
    try:
        topics = load_topics(root)
    except FrontmatterError:
        return 0, 0
    if MODEL_SPECIFIC_ROOT not in topics:
        return 0, 0
    notes = discover_notes(root)
    return len(_retest_lines(notes, topics, today)), len(_reread_lines(notes, topics, today))


def due_requirements(root: Path, today: datetime.date) -> list[str]:
    """One line per concrete requirement whose 'Review by' date is today or earlier, in file order."""
    lines = []
    for number, cells in _requirement_rows(root) or []:
        if (
            _CONCRETE_ID.fullmatch(cells[0])
            and len(cells) == REQUIREMENT_CELLS
            and (due := _iso_date(cells[5]))
            and due <= today
        ):
            lines.append(
                f"{_REQUIREMENTS}:{number}: {cells[0]} due for review since {due}: {cells[1]}"
            )
    return lines
