#!/usr/bin/env python3
"""Measure what each subagent dispatch kept out of the main session and what it cost the main session.

Read-only over ~/.claude/projects. Figures only, no content dumps.
Usage: usage_dispatch_value.py [SESSION_ID_TO_EXCLUDE] [DAYS]

Sources: main transcripts give the dispatch (Agent tool call), its brief, the harness notices and the
main calls around it; subagent transcripts give the run (tool calls, tool results, cost). A run is
linked to its dispatch by `toolUseId` in its `.meta.json`; a run without a dispatch in the window
(nested or older) counts in section A but has no ratio.

Every token figure is an estimate (est.): characters / CHARS_PER_TOKEN, the constant of usage_main_calls.py.
  kept_out   all tool results inside the run: what would have entered the main context had the main
             done the same work itself (an upper bound: the main would have read less or cached it).
  main_side  brief + launch acknowledgement + hand-back frame and report (or the synchronous result)
             + task-notification text that name the run in the main transcript. A notice reaches the
             main as a user record and as a queued_command attachment with different text: it counts
             once per (dispatch, notice id).
  B          main calls with no tool call between the dispatch and its report (the turns spent
             waiting); cache-read USD = their context re-read. Parallel dispatches share waiting
             calls and each row counts a shared call once per dispatch, so the section ends with the
             DISTINCT calls and their USD across all dispatches.
  C          path-like tokens of the report with a file extension that the main then opens itself
             (Read, or Bash whose command contains the path at a path boundary) within REOPEN_CALLS
             main calls; also the number of main calls that opened at least one reported path.
  D          redo = same agent type dispatched within REDO_CALLS main calls after the report with a
             brief sharing at least half of the first brief's paths (at least two).
  E          SendMessage calls; the target type is resolved from the agent id of an earlier launch.
  F          wall-clock seconds from the dispatch to the first report, from record timestamps.
  G          the report of each run: characters and words of its text without the hand-back frame
             (median per agent), the share of `implementer` reports that open with BLOCKED or stop for
             missing input, the share of runs that end within TURN_MARGIN turns of the agent's
             `maxTurns` (frontmatter in plugins/*/agents/; a turn is one deduplicated API call of the
             run), and reviewer dispatches per 100 main calls.
"""

import json
import math
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

ROOT = Path.home() / ".claude" / "projects"
CHARS_PER_TOKEN = 2.98  # calibrated by usage_main_context.py on context growth, same 7-day window
REOPEN_CALLS = 15
REDO_CALLS = 12
MIN_SHARED = 2
RATIO_HIGH = 3  # section A shares: ratio below 1 and below this
FEW_TOOLS, SOME_TOOLS = 2, 5  # section A shares: runs with at most this many tool calls
DEFAULT_DAYS = 7
TURN_MARGIN = 2  # a run ending this close to its agent's maxTurns counts as cap-limited
REPO = Path(__file__).resolve().parents[3]
REVIEWER = "skeptical-reviewer"
# USD per MTok: input, output, cache read (same table as usage_main_context.py).
PRICE = {
    "fable": (8, 40, 0.20),
    "opus": (4, 20, 0.20),
    "sonnet": (2, 10, 0.10),
    "haiku": (0.10, 0.50, 0.01),
}
HAIKU_LONG = (0.50, 2.50, 0.05)  # Haiku prompts over 100K tokens
HAIKU_LONG_PROMPT = 100_000
EXTENSIONS = "py|md|rs|ts|tsx|js|json|jsonl|toml|yaml|yml|sh|txt|css|html|lock|cfg|ini"
PATH_TOKEN = re.compile(rf"[~./\w@+-]*(?:/[\w.@+-]+)+|\b[\w@+-][\w.@+-]*\.(?:{EXTENSIONS})\b")
URL = re.compile(r"https?://\S+")
PLAIN_PAIR = re.compile(r"[A-Za-z]+/[A-Za-z]+")
DIRECTORIES = {"docs", "scripts", "plugins", "src", "tests", "shared", "ports", "agents", "skills"}
AGENT_MESSAGE = re.compile(r'agent-message from="([0-9a-f]+)"')
NOTIFICATION_ID = re.compile(r"<task-id>([0-9a-f]+)</task-id>")
AGENT_ID = re.compile(r"agentId: ([0-9a-f]+)")
FRAME_END = "The report follows:\n"
HANDBACK_END = "\n</agent-message>"
RESULT = re.compile(r"<result>(.*?)</result>", re.DOTALL)
BLOCKED = re.compile(r"^[#*\s]*(?:result:?\s*)?\**blocked\b", re.IGNORECASE)
MISSING_INPUT = re.compile(
    r"missing (?:input|acceptance|scope|brief)|needs? (?:more )?context|cannot proceed",
    re.IGNORECASE,
)
OPENING_LINES = 3
MAX_TURNS = re.compile(r"^maxTurns:\s*(\d+)\s*$", re.MULTILINE)
DELIVERED = "was delivered to you as a message"
LAUNCHED = "Async agent launched"

type Rec = dict[str, Any]


def family(model: object) -> str | None:
    """Return the price family of a model id."""
    return next((name for name in PRICE if name in str(model or "")), None)


def usd(usage: Rec, fam: str) -> tuple[float, float]:
    """Return (total USD, cache-read USD) of one API call."""
    created: Rec = usage.get("cache_creation") or {}
    write_1h = created.get("ephemeral_1h_input_tokens", 0)
    write_5m = created.get("ephemeral_5m_input_tokens", 0)
    if not created:
        write_5m = usage.get("cache_creation_input_tokens", 0)
    plain = usage.get("input_tokens", 0)
    read = usage.get("cache_read_input_tokens", 0)
    p_in, p_out, p_read = PRICE[fam]
    if fam == "haiku" and plain + write_1h + write_5m + read > HAIKU_LONG_PROMPT:
        p_in, p_out, p_read = HAIKU_LONG
    parts = (
        plain * p_in
        + (write_5m * 1.25 + write_1h * 2) * p_in
        + read * p_read
        + usage.get("output_tokens", 0) * p_out
    )
    return parts / 1e6, read * p_read / 1e6


def flat(content: object) -> str:
    """Return the text of a message content or tool result (images count as nothing)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        str(b.get("text", "")) if b.get("type") == "text" else json.dumps(b)
        for b in content
        if isinstance(b, dict) and b.get("type") != "image"
    )


def tokens(chars: float) -> float:
    """Estimate tokens from characters."""
    return chars / CHARS_PER_TOKEN


def records(path: Path, since_iso: str) -> Iterator[Rec]:
    """Yield the transcript records of a file stamped at or after the window start."""
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if line.startswith(('{"type":"api-request', '{"type": "api-request')):
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and (record.get("timestamp") or "") >= since_iso:
                yield record


def blocks(record: Rec) -> list[Rec]:
    """Return the content blocks of a record (a plain string becomes one text block)."""
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def agent_kind(name: object) -> str:
    """Return the agent type without its plugin prefix."""
    return str(name or "general-purpose").rsplit(":", 1)[-1]


def path_tokens(text: str) -> set[str]:
    """Return the path-like tokens of a text (a slash or a known extension; URLs removed)."""
    found: set[str] = set()
    for raw in PATH_TOKEN.findall(URL.sub(" ", text)):
        token = raw.strip(".,;:)(")
        pair = PLAIN_PAIR.fullmatch(token)
        if len(token) >= 4 and not (pair and token.split("/")[0] not in DIRECTORIES):  # ruff: ignore[magic-value-comparison]
            found.add(token)
    return found


@dataclass
class Dispatch:
    """One Agent tool call of a main session and what the main transcript shows around it."""

    tool_id: str
    kind: str
    prompt: str
    call: int
    ts: str
    side_chars: int = 0
    agent_id: str = ""
    report_call: int | None = None
    report_ts: str = ""
    report_text: str = ""
    from_handback: bool = False  # report_text is the hand-back body, not a notification's text
    texts: set[str] = field(default_factory=set)  # kinds of harness text counted in side_chars


@dataclass
class Call:
    """One main API call."""

    cache_read_usd: float = 0.0
    has_tool: bool = False


@dataclass
class Main:
    """What one main transcript yields."""

    calls: list[Call] = field(default_factory=list)
    by_mid: dict[str, int] = field(default_factory=dict)
    dispatches: dict[str, Dispatch] = field(default_factory=dict)
    by_agent: dict[str, Dispatch] = field(default_factory=dict)
    result_chars: dict[str, int] = field(default_factory=dict)
    opens: list[tuple[int, str, str]] = field(default_factory=list)  # call, tool id, haystack
    messages: list[str] = field(default_factory=list)  # SendMessage targets
    seen_notice: set[tuple[str, str, str]] = field(default_factory=set)  # dispatch, notice id, kind


def add_call(main: Main, record: Rec) -> int | None:
    """Register the API call of an assistant record and return its index."""
    message: Rec = record.get("message") or {}
    mid = message.get("id")
    if not mid:
        return None
    if mid not in main.by_mid:
        main.by_mid[mid] = len(main.calls)
        call = Call()
        fam = family(message.get("model"))
        if fam and message.get("usage"):
            call.cache_read_usd = usd(message["usage"], fam)[1]
        main.calls.append(call)
    return main.by_mid[mid]


def add_tool_use(main: Main, block: Rec, index: int, ts: str, claimed: set[str]) -> None:
    """Record a tool call of the main session that the measures use."""
    args: Rec = block.get("input") or {}
    name, tool_id = block.get("name"), str(block.get("id"))
    if name == "Agent" and tool_id not in claimed:
        claimed.add(tool_id)
        prompt = str(args.get("prompt", ""))
        dispatch = Dispatch(tool_id, agent_kind(args.get("subagent_type")), prompt, index, ts)
        dispatch.side_chars = len(json.dumps(args))
        main.dispatches[tool_id] = dispatch
    elif name == "SendMessage":
        main.messages.append(str(args.get("to", "")))
    elif name in {"Read", "Bash"}:
        haystack = str(args.get("file_path" if name == "Read" else "command", ""))
        main.opens.append((index, tool_id, haystack))


def on_assistant(main: Main, record: Rec, claimed: set[str]) -> None:
    """Handle an assistant record of a main transcript."""
    index = add_call(main, record)
    if index is None:
        return
    for block in blocks(record):
        if block.get("type") == "tool_use":
            main.calls[index].has_tool = True
            add_tool_use(main, block, index, record.get("timestamp") or "", claimed)


def report_body(text: str) -> str:
    """Return the report of a harness text without its frame: a hand-back body or a notification result."""
    if FRAME_END in text:
        body = text.split(FRAME_END, 1)[1].split(HANDBACK_END, 1)[0]
        return "\n".join(line.removeprefix("  ") for line in body.splitlines())
    found = RESULT.search(text)
    return found.group(1).strip() if found else text


def mark_report(main: Main, dispatch: Dispatch, ts: str, text: str, handback: bool = False) -> None:
    """Note the first report of a dispatch (when it arrived) and its text.

    The text comes from the first report; the hand-back body replaces a notification's text when it
    arrives later, because it is the report itself.
    """
    if dispatch.report_call is None:
        dispatch.report_call = len(main.calls)
        dispatch.report_ts = ts
        dispatch.report_text = report_body(text)
        dispatch.from_handback = handback
    elif handback and not dispatch.from_handback:
        dispatch.report_text = report_body(text)
        dispatch.from_handback = True


def on_tool_result(main: Main, block: Rec, ts: str) -> None:
    """Handle a tool result of a main transcript: sizes, launch acknowledgement or sync report."""
    tool_id = str(block.get("tool_use_id"))
    text = flat(block.get("content"))
    main.result_chars[tool_id] = len(text)
    dispatch = main.dispatches.get(tool_id)
    if dispatch is None:
        return
    dispatch.side_chars += len(text)
    found = AGENT_ID.search(text)
    if found:
        dispatch.agent_id = found.group(1)
        main.by_agent[dispatch.agent_id] = dispatch
    if LAUNCHED not in text:
        mark_report(main, dispatch, ts, text)


def on_notice(main: Main, text: str, ts: str) -> None:
    """Handle harness text of the main transcript: a hand-back or a task-notification."""
    handback = AGENT_MESSAGE.search(text[:400])
    notification = NOTIFICATION_ID.search(text[:600]) if "<task-notification>" in text else None
    found = handback or notification
    dispatch = main.by_agent.get(found.group(1)) if found else None
    if found is None or dispatch is None:
        return
    # The hand-back message and the completion notification are two texts of one dispatch that both
    # enter the main context: each counts once.
    kind = "handback" if handback else "notification"
    key = (dispatch.tool_id, found.group(1), kind)
    if key in main.seen_notice:
        return
    main.seen_notice.add(key)
    dispatch.texts.add(kind)
    dispatch.side_chars += len(text)
    if handback or DELIVERED not in text:
        mark_report(main, dispatch, ts, text, handback=bool(handback))


def on_user(main: Main, record: Rec) -> None:
    """Handle a user record of a main transcript."""
    ts = record.get("timestamp") or ""
    for block in blocks(record):
        if block.get("type") == "tool_result":
            on_tool_result(main, block, ts)
        elif block.get("type") == "text":
            on_notice(main, str(block.get("text", "")), ts)


def on_attachment(main: Main, record: Rec) -> None:
    """Handle a queued command attachment (where hand-backs and notifications arrive)."""
    attachment: Rec = record.get("attachment") or {}
    if attachment.get("type") == "queued_command":
        text = attachment.get("prompt") or record.get("rendered") or ""
        on_notice(
            main, text if isinstance(text, str) else flat(text), record.get("timestamp") or ""
        )


def parse_main(path: Path, since_iso: str, claimed: set[str]) -> Main:
    """Read one main transcript."""
    main = Main()
    handlers: dict[str, Callable[[Rec], None]] = {
        "assistant": lambda r: on_assistant(main, r, claimed),
        "user": partial(on_user, main),
        "attachment": partial(on_attachment, main),
    }
    for record in records(path, since_iso):
        handler = handlers.get(str(record.get("type")))
        if handler:
            handler(record)
    return main


@dataclass
class Run:
    """One subagent run."""

    kind: str
    tool_id: str
    agent_id: str
    tool_uses: int = 0
    turns: int = 0
    kept_chars: int = 0
    cost: float = 0.0


def parse_run(path: Path, since_iso: str) -> Run | None:
    """Read one subagent transcript with its meta file; None when it has no API call in the window."""
    try:
        meta: Rec = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    run = Run(
        agent_kind(meta.get("agentType") or "workflow"),
        str(meta.get("toolUseId", "")),
        path.stem.removeprefix("agent-"),
    )
    seen_mid: set[str] = set()
    seen_tool: set[str] = set()
    for record in records(path, since_iso):
        if record.get("type") == "assistant":
            collect_assistant(run, record, seen_mid, seen_tool)
        elif record.get("type") == "user":
            run.kept_chars += sum(
                len(flat(b.get("content")))
                for b in blocks(record)
                if b.get("type") == "tool_result"
            )
    run.turns = len(seen_mid)
    return run if seen_mid else None


def collect_assistant(run: Run, record: Rec, seen_mid: set[str], seen_tool: set[str]) -> None:
    """Add the cost and tool calls of an assistant record to a run."""
    message: Rec = record.get("message") or {}
    fam = family(message.get("model"))
    mid = message.get("id")
    if mid and mid not in seen_mid and message.get("usage") and fam:
        seen_mid.add(mid)
        run.cost += usd(message["usage"], fam)[0]
    for block in blocks(record):
        if block.get("type") == "tool_use" and block.get("name") != "SubagentHandback":
            seen_tool.add(str(block.get("id")))
    run.tool_uses = len(seen_tool)


def duration(dispatch: Dispatch) -> float | None:
    """Return seconds from the dispatch to its first report."""
    if not dispatch.report_ts or not dispatch.ts:
        return None
    start = datetime.fromisoformat(dispatch.ts)
    return (datetime.fromisoformat(dispatch.report_ts) - start).total_seconds()


def waiting_calls(main: Main, dispatch: Dispatch) -> list[int]:
    """Return the indexes of the main calls without a tool call between the dispatch and its report.

    A dispatch that never reported counts the text-only calls that follow it until the main's next
    tool call: after that the main is no longer waiting for it.
    """
    if dispatch.report_call is not None:
        end = dispatch.report_call
        return [i for i in range(dispatch.call + 1, end) if not main.calls[i].has_tool]
    waiting: list[int] = []
    for index in range(dispatch.call + 1, len(main.calls)):
        if main.calls[index].has_tool:
            break
        waiting.append(index)
    return waiting


def reopened(main: Main, dispatch: Dispatch) -> tuple[int, float, int]:
    """Return (distinct report paths opened soon after, est. tokens of those results, calls that opened one)."""
    if dispatch.report_call is None:
        return 0, 0.0, 0
    first = dispatch.report_call
    window = [o for o in main.opens if first <= o[0] < first + REOPEN_CALLS]
    hit: set[str] = set()
    chars: dict[str, int] = {}
    calls: set[int] = set()
    for path in (t for t in path_tokens(dispatch.report_text) if Path(t).suffix):
        # boundary on both sides: `foo.md` matches `foo.md:3` and `foo.md.`, not `foo.mdx` or `foo.md-old`
        at_boundary = re.compile(rf"(?:^|[\s'\"/]){re.escape(path)}(?![\w@+-]|\.\w)")
        for index, tool_id, haystack in window:
            if at_boundary.search(haystack):
                hit.add(path)
                calls.add(index)
                chars[tool_id] = main.result_chars.get(tool_id, 0)
    return len(hit), tokens(sum(chars.values())), len(calls)


def is_redo(main: Main, dispatch: Dispatch) -> bool:
    """Tell whether the same agent type was dispatched again on mostly the same paths."""
    if dispatch.report_call is None:
        return False
    first = path_tokens(dispatch.prompt)
    need = max(MIN_SHARED, math.ceil(len(first) / 2))
    first_call = dispatch.report_call
    return any(
        other.kind == dispatch.kind
        and other is not dispatch
        and first_call <= other.call < first_call + REDO_CALLS
        and len(first & path_tokens(other.prompt)) >= need
        for other in main.dispatches.values()
    )


def median(values: list[float]) -> float:
    """Return the median, or 0 for no values."""
    return statistics.median(values) if values else 0.0


def share(values: list[bool]) -> float:
    """Return the percentage of true values."""
    return 100 * sum(values) / len(values) if values else 0.0


def table(title: str, header: list[str], rows: list[list[str]]) -> None:
    """Print an aligned table with its title."""
    print(f"\n## {title}")
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    for row in [header, *rows]:
        print(
            "  "
            + "  ".join(
                c.ljust(widths[0]) if i == 0 else c.rjust(widths[i]) for i, c in enumerate(row)
            )
        )


def by_kind[T](
    items: list[T], kind_of: Callable[[T], str], order: list[str]
) -> list[tuple[str, list[T]]]:
    """Group items by agent type in the given order, then add the total row."""
    groups: dict[str, list[T]] = defaultdict(list)
    for item in items:
        groups[kind_of(item)].append(item)
    return [(k, groups[k]) for k in order if k in groups] + [("TOTAL", items)]


def section_a(runs: list[Run], dispatches: dict[str, Dispatch], order: list[str]) -> None:
    """Print section A: value per dispatch."""
    header = ["agent", "runs", "linked", "tools_med", "kept_out_med", "main_side_med", "ratio_med",
              "ratio<1%", "ratio<3%", "tools<=2%", "tools<=5%", "usd_sum", "usd_med"]  # fmt: skip
    rows: list[list[str]] = []
    for name, group in by_kind(runs, lambda r: r.kind, order):
        linked = [(r, dispatches[r.tool_id]) for r in group if r.tool_id in dispatches]
        ratios = [tokens(r.kept_chars) / max(tokens(d.side_chars), 1) for r, d in linked]
        rows.append([
            name, str(len(group)), str(len(linked)),
            f"{median([r.tool_uses for r in group]):.0f}",
            f"{median([tokens(r.kept_chars) for r in group]):.0f}",
            f"{median([tokens(d.side_chars) for _, d in linked]):.0f}",
            f"{median(ratios):.1f}",
            f"{share([x < 1 for x in ratios]):.0f}", f"{share([x < RATIO_HIGH for x in ratios]):.0f}",
            f"{share([r.tool_uses <= FEW_TOOLS for r in group]):.0f}",
            f"{share([r.tool_uses <= SOME_TOOLS for r in group]):.0f}",
            f"{sum(r.cost for r in group):.1f}", f"{median([r.cost for r in group]):.2f}",
        ])  # fmt: skip
    table("A. Value per dispatch (tokens est.; kept_out is an upper bound)", header, rows)


Item = tuple[Main, Dispatch]


def section_b(items: list[Item], order: list[str]) -> None:
    """Print section B: main calls spent waiting per dispatch, then the distinct calls overall."""
    rows: list[list[str]] = []
    for name, group in by_kind(items, lambda i: i[1].kind, order):
        waits = [(m, waiting_calls(m, d)) for m, d in group]
        counts = [float(len(w)) for _, w in waits]
        unreported = sum(1 for _, d in group if d.report_call is None)
        rows.append([
            name, str(len(waits)), str(unreported), f"{median(counts):.0f}",
            f"{statistics.fmean(counts) if counts else 0:.2f}", f"{sum(counts):.0f}",
            f"{sum(m.calls[i].cache_read_usd for m, w in waits for i in w):.2f}",
        ])  # fmt: skip
    table(
        "B. Main calls without a tool call before the report, per dispatch; a dispatch that never "
        "reported counts the text-only calls right after it "
        "(parallel dispatches share calls: a row counts a shared call once per dispatch)",
        ["agent", "dispatches", "unreported", "median", "mean", "calls", "cache_read_usd"],
        rows,
    )
    distinct = {(id(m), i): m.calls[i] for m, d in items for i in waiting_calls(m, d)}
    usd_sum = sum(c.cache_read_usd for c in distinct.values())
    print(
        f"  distinct waiting calls across all dispatches: {len(distinct)}, cache_read_usd {usd_sum:.2f}"
    )


def section_c(items: list[Item], order: list[str]) -> None:
    """Print section C: re-reading after a report."""
    rows: list[list[str]] = []
    for name, group in by_kind(items, lambda i: i[1].kind, order):
        found = [reopened(m, d) for m, d in group if d.report_call is not None]
        rows.append([
            name, str(len(found)), f"{share([n > 0 for n, _, _ in found]):.0f}",
            f"{statistics.fmean([n for n, _, _ in found]) if found else 0:.2f}",
            f"{sum(t for _, t, _ in found):.0f}",
            str(sum(c for _, _, c in found)),
            f"{statistics.fmean([c for _, _, c in found]) if found else 0:.2f}",
        ])  # fmt: skip
    table(
        "C. Paths of a report re-opened by the main within 15 calls (tokens est.)",
        [
            "agent",
            "reports",
            "followed%",
            "opens_mean",
            "tokens_total",
            "calls_total",
            "calls_mean",
        ],
        rows,
    )


def section_d(items: list[Item], order: list[str]) -> None:
    """Print section D: redo share and round 2 briefs."""
    rows: list[list[str]] = []
    for name, group in by_kind(items, lambda i: i[1].kind, order):
        reported = [(m, d) for m, d in group if d.report_call is not None]
        redo = [is_redo(m, d) for m, d in reported]
        round2 = [bool(re.search(r"round 2", d.prompt, re.IGNORECASE)) for _, d in group]
        rows.append([
            name, str(len(reported)), f"{share(redo):.1f}", str(sum(redo)),
            str(len(group)), str(sum(round2)),
        ])  # fmt: skip
    table(
        "D. Re-dispatch within 12 calls, and briefs with 'round 2'",
        ["agent", "reports", "redo%", "redos", "briefs", "round2"],
        rows,
    )


def section_e(mains: list[Main]) -> None:
    """Print section E: follow-up messages."""
    count: Counter[str] = Counter()
    for main in mains:
        for target in main.messages:
            dispatch = main.by_agent.get(target)
            count[dispatch.kind if dispatch else "unresolved"] += 1
    rows = [[k, str(v)] for k, v in count.most_common()] + [["TOTAL", str(sum(count.values()))]]
    table("E. SendMessage follow-ups by target agent type", ["agent", "messages"], rows)


def section_f(items: list[Item], order: list[str]) -> None:
    """Print section F: seconds from dispatch to report."""
    rows: list[list[str]] = []
    for name, group in by_kind(items, lambda i: i[1].kind, order):
        secs = [s for _, d in group if (s := duration(d)) is not None]
        rows.append([name, str(len(secs)), f"{median(secs):.0f}", f"{max(secs, default=0):.0f}"])
    table("F. Seconds from dispatch to report", ["agent", "measured", "median", "max"], rows)


def max_turns() -> dict[str, int]:
    """Return the `maxTurns` of each agent type, read from the agent frontmatter of the plugins."""
    caps: dict[str, int] = {}
    for path in sorted(REPO.glob("plugins/*/agents/*.md")):
        found = MAX_TURNS.search(path.read_text(encoding="utf-8").split("\n---", 2)[0])
        if found:
            caps[path.stem] = int(found.group(1))
    return caps


def opens_blocked(text: str) -> bool:
    """Tell whether a report opens with BLOCKED or stops for missing input (its first lines say so)."""
    head = [line for line in text.splitlines() if line.strip()][:OPENING_LINES]
    return bool(head) and (
        bool(BLOCKED.match(head[0])) or any(MISSING_INPUT.search(line) for line in head)
    )


def near_cap(run: Run, caps: dict[str, int]) -> bool | None:
    """Tell whether a run ended within TURN_MARGIN turns of its agent's cap; None when it has none."""
    cap = caps.get(run.kind)
    return None if cap is None else run.turns >= cap - TURN_MARGIN


def section_g(items: list[Item], runs: list[Run], order: list[str], total_calls: int) -> None:
    """Print section G: report size, blocked share, turn cap and reviewer dispatches per 100 main calls."""
    caps = max_turns()
    rows: list[list[str]] = []
    for name, group in by_kind(items, lambda i: i[1].kind, order):
        texts = [d.report_text for _, d in group if d.report_call is not None]
        kind_runs = [r for r in runs if name in {r.kind, "TOTAL"}]
        capped = [x for r in kind_runs if (x := near_cap(r, caps)) is not None]
        rows.append([
            name, str(len(texts)),
            f"{median([len(t) for t in texts]):.0f}", f"{median([len(t.split()) for t in texts]):.0f}",
            f"{share([opens_blocked(t) for t in texts]):.1f}",
            str(caps.get(name, "-")), str(len(capped)), f"{share(capped):.1f}",
        ])  # fmt: skip
    table(
        "G. Report text without its frame, blocked share, and runs within "
        f"{TURN_MARGIN} turns of maxTurns (TOTAL covers agents with a cap)",
        ["agent", "reports", "chars_med", "words_med", "blocked%", "maxTurns", "runs", "near_cap%"],
        rows,
    )
    reviewer = sum(1 for _, d in items if d.kind == REVIEWER)
    per_100 = 100 * reviewer / total_calls if total_calls else 0.0
    print(f"  reviewer dispatches {reviewer} per 100 main calls ({total_calls}): {per_100:.2f}")
    both = sum(1 for _, d in items if len(d.texts) == 2)  # ruff: ignore[magic-value-comparison]
    print(f"  dispatches whose hand-back and notification both entered the main: {both}")


def main() -> None:
    """Print the six sections for the last DAYS days."""
    args = sys.argv[1:]
    skip = args[0] if args else "\0"
    days = int(args[1]) if args[1:] else DEFAULT_DAYS
    since = time.time() - days * 86400
    since_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(since))
    paths = [p for p in ROOT.glob("**/*.jsonl") if p.stat().st_mtime > since and skip not in str(p)]
    claimed: set[str] = set()
    mains = [parse_main(p, since_iso, claimed) for p in paths if "/subagents/" not in str(p)]
    runs = [r for p in paths if "/subagents/" in str(p) and (r := parse_run(p, since_iso))]
    dispatches = {t: d for m in mains for t, d in m.dispatches.items()}
    items: list[Item] = [(m, d) for m in mains for d in m.dispatches.values()]
    order = [k for k, _ in Counter(r.kind for r in runs).most_common()]
    order += [k for k, _ in Counter(d.kind for _, d in items).most_common() if k not in order]
    print(
        f"window {days} days, main sessions {len(mains)}, runs {len(runs)}, dispatches {len(items)}"
    )
    print(
        f"chars per token {CHARS_PER_TOKEN} (fixed, as usage_main_calls.py); skip session {skip[:8]}"
    )
    section_a(runs, dispatches, order)
    section_b(items, order)
    section_c(items, order)
    section_d(items, order)
    section_e(mains)
    section_f(items, order)
    section_g(items, runs, order, sum(len(m.calls) for m in mains))


if __name__ == "__main__":
    main()
