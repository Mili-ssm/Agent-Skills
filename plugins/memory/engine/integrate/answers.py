"""The lines of a model session's answer: only rows, `none` and `#` comments are accepted."""

from __future__ import annotations

from integrate.rows import parse_rows

_FENCE = "```"


def _is_row(line: str) -> bool:
    rows, bad = parse_rows(line)
    return len(rows) == 1 and not bad


def answer_lines(answer: str) -> list[str] | None:
    """The answer's lines (fences and blank lines dropped), or None when it is empty or any line is neither a row, `none` nor a `#` comment."""
    lines = [
        text
        for line in answer.splitlines()
        if (text := line.strip()) and not text.startswith(_FENCE)
    ]
    if not lines:
        return None
    if all(line == "none" or line.startswith("#") or _is_row(line) for line in lines):
        return lines
    return None
