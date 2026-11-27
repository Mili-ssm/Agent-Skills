"""Small helpers shared by the corroboration background jobs."""

from __future__ import annotations


def finish(result: dict, **changes) -> dict:
    """Apply final result fields and normalize accumulated model cost."""
    result.update(changes)
    result["cost"] = round(result["cost"], 6)
    return result


def cell(text: object) -> str:
    """Format one value for a Markdown table cell."""
    return " ".join(str(text or "").split()).replace("|", "\\|")
