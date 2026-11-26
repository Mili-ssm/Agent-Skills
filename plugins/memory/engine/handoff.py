"""Parse the handoff block an agent writes at the end of a compaction summary.

Pure and standard-library only. Lenient on Markdown around the marker and the
field names, so a compliant model is never reported as non-compliant.
"""

import os
import re
from pathlib import Path

FIELDS: tuple[str, ...] = ("task", "state", "next", "verified", "unverified", "plan")

INSTRUCTION = """End the summary with this block, one line per field, so the next context resumes from it:
HANDOFF
task: <the task in progress, in one sentence>
state: <what is done>
next: <the next step>
verified: <what a check or the owner confirmed>
unverified: <what is claimed but not checked>
plan: <path of the active plan file, or "no plan">
Before the block, list every decision, constraint, pitfall or finding of this session that was not yet recorded with mem remember, one per line, each line starting with "not yet recorded:", so that the next context can record them."""

_MARKER_STRIP = "#*->`: \t"
_FIELD = re.compile(
    r"^[\s\-*>]*(?:\*\*)?(" + "|".join(FIELDS) + r")(?:\*\*)?\s*:(?:\*\*)?\s*(.*)$", re.IGNORECASE
)
_UNRECORDED = "not yet recorded:"
_PLAN_TOKEN = re.compile(r"[^\s'\"`\[\]()<>,;*]+\.md(?!\w)", re.IGNORECASE)
_NO_BLOCK = "The summary has no handoff block: state the task, its state and the next step before you continue."
_MAX_VALUE = 500  # bounds the regex work on hostile text
_NONE = {"none", "nothing"}
_MARKER_LINE = 40
_MAX_TOKEN = 60  # keeps the whole line under 150 characters


def has_marker(summary: str) -> bool:
    """True when a short line (a heading or label) names the handoff; the word inside a sentence does not count."""
    return any(
        "handoff" in line.lower() and len(line.strip()) <= _MARKER_LINE
        for line in summary.splitlines()
    )


def _marker_index(lines: list[str]) -> int | None:
    marker = None
    for i, line in enumerate(lines):
        if line.strip(_MARKER_STRIP).lower() == "handoff":
            marker = i
    return marker


def _field_of(line: str) -> tuple[str, str] | None:
    if line.lstrip().startswith("```"):
        return None
    m = _FIELD.match(line)
    if not m:
        return None
    value = m.group(2).strip()
    if value.startswith("<") and value.endswith(">") and " " in value:
        return None  # an echoed template placeholder is a phrase; <docs/p.md> is a path
    return m.group(1).lower(), value[:_MAX_VALUE]


def parse(summary: str) -> dict[str, str]:
    lines = summary.splitlines()
    marker = _marker_index(lines)
    if marker is None:
        return {}
    found: dict[str, str] = {}
    for line in lines[marker + 1 :]:
        field = _field_of(line)
        if field:
            found.setdefault(*field)
    return found


def unrecorded(summary: str) -> int:
    count = 0
    in_list = False
    for line in summary.splitlines():
        stripped = line.strip()
        head = stripped.lstrip("-* \t")
        if head.lower().startswith(_UNRECORDED):
            rest = head[len(_UNRECORDED) :].strip("*` \t")
            none = rest.rstrip(".").strip("*` \t").lower() in _NONE
            if rest and not none:
                count += 1
            in_list = not rest  # only a bare header opens a list; "none" closes it
        elif in_list and stripped[:1] in {"-", "*"}:
            count += 1
        else:
            in_list = False
    return count


def _project_root(cwd: Path) -> Path:
    cwd = Path(os.path.realpath(cwd))
    for d in (cwd, *cwd.parents):
        if os.path.lexists(d / ".git"):
            return d
    return cwd


def _plan_token(value: str) -> str | None:
    value = value[:_MAX_VALUE]
    if "://" in value:
        return None
    m = _PLAN_TOKEN.search(value)
    return m.group(0) if m else None


def names_plan(value: str) -> bool:
    return _plan_token(value) is not None


def _accepts(root: Path, candidate: str, token: str) -> bool:
    """True when this candidate ends the search with no mismatch to report."""
    try:
        target = Path(os.path.realpath(root / candidate))  # an absolute path replaces root
        if root != target and root not in target.parents:
            return candidate == token
        return os.path.isfile(target)
    except (OSError, ValueError):
        return True


def mismatches(found: dict[str, str], cwd: Path) -> list[str]:
    if not found:
        return [_NO_BLOCK]
    plan = found.get("plan", "")[:_MAX_VALUE]
    token = _plan_token(plan)
    if token is None:
        return []
    root = _project_root(Path(cwd))
    if any(_accepts(root, candidate, token) for candidate in (token, plan.strip("'\"`* \t"))):
        return []
    return [
        f"The handoff names a plan file that does not exist: {token[:_MAX_TOKEN]}. Find the plan before you continue."
    ]
