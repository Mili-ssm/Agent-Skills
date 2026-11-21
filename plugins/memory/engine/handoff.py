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
_FIELD = re.compile(r"^[\s\-*>]*(?:\*\*)?(" + "|".join(FIELDS) + r")(?:\*\*)?\s*:(?:\*\*)?\s*(.*)$", re.I)
_UNRECORDED = "not yet recorded:"
_PLAN_TOKEN = re.compile(r"[^\s'\"`\[\]()<>,;]+\.md(?!\w)", re.I)
_NO_BLOCK = "The summary has no handoff block: state the task, its state and the next step before you continue."
_MAX_TOKEN = 60  # keeps the whole line under 150 characters


def has_marker(summary: str) -> bool:
    return "handoff" in summary.lower()


def parse(summary: str) -> dict[str, str]:
    lines = summary.splitlines()
    marker = None
    for i, line in enumerate(lines):
        if line.strip(_MARKER_STRIP).lower() == "handoff":
            marker = i
    if marker is None:
        return {}
    found: dict[str, str] = {}
    for line in lines[marker + 1:]:
        if line.lstrip().startswith("```"):
            continue
        m = _FIELD.match(line)
        if m:
            found.setdefault(m.group(1).lower(), m.group(2).strip())
    return found


def unrecorded(summary: str) -> int:
    count = 0
    in_list = False
    for line in summary.splitlines():
        stripped = line.strip()
        head = stripped.lstrip("-* \t")
        if head.lower().startswith(_UNRECORDED):
            rest = head[len(_UNRECORDED):].strip("*` \t")
            if rest:
                count += 1
                in_list = False
            else:
                in_list = True
        elif in_list and stripped[:1] in ("-", "*"):
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


def mismatches(found: dict[str, str], cwd: Path) -> list[str]:
    if not found:
        return [_NO_BLOCK]
    m = _PLAN_TOKEN.search(found.get("plan", ""))
    if not m:
        return []
    token = m.group(0)
    root = _project_root(Path(cwd))
    try:
        target = Path(os.path.realpath(root / token))  # an absolute token replaces root
        if root != target and root not in target.parents:
            return []
        if target.is_file():
            return []
    except (OSError, ValueError):
        return []
    return [f"The handoff names a plan file that does not exist: {token[:_MAX_TOKEN]}. Find the plan before you continue."]
