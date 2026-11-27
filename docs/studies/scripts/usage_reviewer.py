"""Count skeptical-reviewer dispatches by trigger and the severity mix of its reports.

Read-only over ~/.claude/projects. Figures only, no content dumps.
Usage: usage_reviewer.py [DAYS]

Dispatches come from the main transcripts (the Agent tool call and its brief); reports come from
the reviewer's own subagent transcripts (its SubagentHandback message, else its last text).
The trigger of a dispatch is guessed from words in its brief, so read the kinds as estimates.
"""

import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import cast

ROOT = Path.home() / ".claude" / "projects"
AGENT = "skeptical-reviewer"
SEVERITIES = ("low", "medium", "high")
SEVERITY_CELL = 3  # the format before the Category column was dropped
KINDS = {
    "round 2": re.compile(r"round[^a-z0-9]{0,4}2|second round"),
    "process": re.compile(r"process review|steps taken|steps i took"),
    "push or PR": re.compile(r"before (a |the )?(push|pull request|pr|merge|tag)\b|pre-push"),
    "plan task": re.compile(r"task \d+"),
}

type Block = dict[str, object]


def blocks(line: str) -> list[Block]:
    """Return the content blocks of one transcript line, or nothing when it has none."""
    try:
        record = cast("dict[str, object]", json.loads(line))
    except json.JSONDecodeError:
        return []
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = cast("dict[str, object]", message).get("content")
    if not isinstance(content, list):
        return []
    return [cast("Block", b) for b in cast("list[object]", content) if isinstance(b, dict)]


def tool_input(block: Block) -> dict[str, object]:
    """Return the input of a tool_use block."""
    value = block.get("input")
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def transcript_blocks(path: Path, needle: str = "") -> Iterator[Block]:
    """Yield the content blocks of a transcript, skipping lines without the needle."""
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if needle in line:
                yield from blocks(line)


def briefs(since: float) -> list[tuple[str, str]]:
    """Return (session, brief) for each reviewer dispatch in main transcripts changed since."""
    found: dict[str, tuple[str, str]] = {}
    for path in ROOT.glob("*/*.jsonl"):
        if path.stat().st_mtime < since:
            continue
        for block in transcript_blocks(path, AGENT):
            args = tool_input(block)
            if block.get("type") == "tool_use" and str(args.get("subagent_type", "")).endswith(
                AGENT
            ):
                found[str(block.get("id"))] = (path.stem, str(args.get("prompt", "")))
    return list(found.values())


def agent_type(meta: Path) -> str:
    """Return the agent type a subagent's meta file names, or nothing when unreadable."""
    try:
        return str(
            cast("dict[str, object]", json.loads(meta.read_text(encoding="utf-8"))).get(
                "agentType", ""
            )
        )
    except json.JSONDecodeError:
        return ""


def final_report(transcript: Path) -> str:
    """Return a subagent's hand-back message, else its last text."""
    last = ""
    for block in transcript_blocks(transcript):
        text = block.get("text")
        if block.get("type") == "text" and isinstance(text, str) and text.strip():
            last = text
        if block.get("type") == "tool_use" and block.get("name") == "SubagentHandback":
            last = str(tool_input(block).get("message") or last)
    return last


def reports(since: float) -> list[str]:
    """Return the final report of each reviewer run changed since."""
    found: list[str] = []
    for meta in ROOT.rglob("*.meta.json"):
        transcript = meta.with_name(meta.name.removesuffix(".meta.json") + ".jsonl")
        if (
            transcript.exists()
            and transcript.stat().st_mtime >= since
            and agent_type(meta).endswith(AGENT)
        ):
            found.append(final_report(transcript))
    return found


def kind(brief: str) -> str:
    """Guess what triggered a dispatch from the words of its brief."""
    lowered = brief.lower()
    names = [name for name, pattern in KINDS.items() if pattern.search(lowered)]
    return " + ".join(names) or "final answer or ad hoc"


def severity_cell(report: str) -> int:
    """Return the index of the Severity column in the report's table header, or the old default."""
    for row in report.splitlines():
        cells = [cell.strip().lower() for cell in row.split("|")]
        if "severity" in cells:
            return cells.index("severity")
    return SEVERITY_CELL


# A section label of the report format: `Low:`, `Not checked:` or `Left out:` (a count in parentheses
# is allowed), then whitespace or the line end. Only these end a Low block, so a finding line like
# `Makefile: typo`, `Makefile:3 — …` or `a.py:12 — …` does not.
LABEL = re.compile(r"(?:Low|Not checked|Left out)(?: ?\(\d+\))?:(?!\S)")
LEFT_OUT = re.compile(r"Left out:\s*(\d+)\s+low\b", re.IGNORECASE)


def severities(report: str) -> Counter[str]:
    """Count the findings of a report by severity.

    Table rows count by their Severity cell; lines after a `Low:` label count as low until the next
    label or a blank line; K of a `Left out: K low findings` line is added to the low count.
    """
    count: Counter[str] = Counter()
    cell = severity_cell(report)
    in_low = False
    for row in report.splitlines():
        if re.match(r"\|\s*\d+\s*\|", row):
            cells = [text.strip().lower() for text in row.split("|")]
            if len(cells) > cell and cells[cell] in SEVERITIES:
                count[cells[cell]] += 1
        left_out = LEFT_OUT.match(row)
        if left_out:
            count["low"] += int(left_out.group(1))
        in_low = row.startswith("Low") if LABEL.match(row) else in_low and bool(row.strip())
        count["low"] += in_low and not row.startswith("Low")
    return count


def spread(values: list[int]) -> str:
    """Format the median and the 90th percentile."""
    if not values:
        return "none"
    p90 = sorted(values)[max(0, math.ceil(round(0.9 * len(values), 9)) - 1)]  # nearest rank
    return f"median {statistics.median(values):.0f}, p90 {p90}"


def main() -> None:
    """Print the dispatch and report figures for the last DAYS days."""
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    since = time.time() - days * 86400
    dispatched = briefs(since)
    per_session = Counter(session for session, _ in dispatched)
    print(f"dispatches {len(dispatched)} in {len(per_session)} sessions over {days} days")
    print(f"dispatches per session: {spread(list(per_session.values()))}")
    print(f"brief chars: {spread([len(brief) for _, brief in dispatched])}")
    for name, runs in Counter(kind(brief) for _, brief in dispatched).most_common():
        print(f"  {runs:4d}  {name}")

    rows: Counter[str] = Counter()
    zero = with_medium_or_high = with_high = 0
    parsed: list[str] = []
    for report in reports(since):
        header = re.search(r"## Findings \((\d+)", report)
        if not header:
            continue
        parsed.append(report)
        found = severities(report)
        rows.update(found)
        zero += header.group(1) == "0"
        with_medium_or_high += bool(found["medium"] or found["high"])
        with_high += bool(found["high"])
    total = max(len(parsed), 1)
    print(f"reports with a Findings header: {len(parsed)}")
    print(
        f"  zero findings {100 * zero // total}% · any medium or high {100 * with_medium_or_high // total}%"
        f" · any high {100 * with_high // total}%"
    )
    print(f"  finding rows by severity: {dict(rows)}")
    print(f"  report chars: {spread([len(report) for report in parsed])}")
    print(f"  report words: {spread([len(report.split()) for report in parsed])}")


if __name__ == "__main__":
    main()
