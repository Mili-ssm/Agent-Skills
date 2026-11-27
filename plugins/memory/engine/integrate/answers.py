"""The lines of a model session's answer: only rows, `none` and `#` comments are accepted."""

from __future__ import annotations

import re

from integrate.rows import row_of

_FENCE = "```"
_FENCE_LINE = re.compile(r"```[A-Za-z]*")


def _is_valid(line: str) -> bool:
    return line == "none" or line.startswith("#") or row_of(line) is not None


def _content_lines(answer: str) -> list[str] | None:
    """Non-blank lines without fence lines; None when a line starts with a fence but is not one."""
    lines: list[str] = []
    for text in filter(None, (line.strip() for line in answer.splitlines())):
        if not text.startswith(_FENCE):
            lines.append(text)
        elif not _FENCE_LINE.fullmatch(text):
            return None
    return lines


def answer_lines(answer: str) -> list[str] | None:
    """The answer's lines (fence and blank lines dropped), or None.

    None when it is empty or only comments (it decides nothing), any line is neither a row, `none` nor a `#`
    comment, a line starts with a fence but is not just a fence, or `none` comes with a row (a contradictory
    answer applies nothing).
    """
    lines = _content_lines(answer)
    if lines is None or not all(_is_valid(line) for line in lines):
        return None
    if all(line.startswith("#") for line in lines):
        return None
    if "none" in lines and any(line != "none" and not line.startswith("#") for line in lines):
        return None
    return lines
