"""Count what the main Claude Code session spends its API calls on and which operations look avoidable.

Read-only over ~/.claude/projects. Figures only, no content dumps.
Usage: usage_main_calls.py [SESSION_ID_TO_EXCLUDE] [DAYS]

A main call is one deduplicated assistant API response in a main transcript (subagent transcripts are
skipped). The trigger of a call is what reached the main between the previous call and this one.
Token figures marked "est." are characters divided by CHARS_PER_TOKEN.
"""

import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

ROOT = Path.home() / ".claude" / "projects"
CHARS_PER_TOKEN = 2.98  # calibrated by usage_main_context.py on context growth, same 7-day window
# USD per MTok: input, output, cache read (same table as usage_main_context.py).
PRICE = {
    "fable": (8.0, 40.0, 0.20),
    "opus": (4.0, 20.0, 0.20),
    "sonnet": (2.0, 10.0, 0.10),
    "haiku": (0.10, 0.50, 0.01),
}
HAIKU_LONG = (0.50, 2.50, 0.05)  # Haiku prompts over 100K tokens
LONG_PROMPT = 100_000
SEARCH_TOOLS = ("Grep", "Glob")
LOOKUP_BASH = ("read-file", "search", "git/gh", "mem")
CHECK = re.compile(
    r"\b(pytest|cargo (test|build|clippy|check|fmt|run)|validate\.py|npm (run|test)|ruff"
    r"|plugin (eval|validate|test)|tsc|port\.py|mypy|uv run)\b"
)
MEM = re.compile(r"(^|[;&|]\s*)mem\b")
# A command that changes state is not a lookup, even when its class is git/gh, mem or read-file.
MUTATING = re.compile(
    r"\bgit\s+(-[Cc]\s+(\"[^\"]*\"|'[^']*'|\S+)\s+|-\S+\s+)*"
    r"(commit|push|merge|rebase|reset|checkout|switch|add|stash|tag|cherry-pick|restore|rm|mv)\b"
    r"|\bgh\s+(pr\s+(create|merge|close|comment|edit)|issue\s+(create|close|comment)|release)\b"
    r"|(^|[;&|]\s*)mem\s+(remember|forget|settle|synthesis|curate\s+apply|confirm|observe|refute"
    r"|supersede|merge|distinct|restore|promote|triage|note|new|rename|import|import-recover|unify"
    r"|init|index|install-command|fetch-sources)\b"
    r"|\bsed\b[^;&|\n]*\s(-[A-Za-z]*i\b|--in-place)"
    r"|\btee\s+(-\S+\s+)*[^-\s]"
    # a redirect to a file; not `2>&1`, `>&2`, `> /dev/null`, `->`, `=>`
    r"|(?<![-=>&|])>>?(?![>&=])\s*(?!/dev/null\b)[^\s&|;)]"
)
TASK_ID = re.compile(r"<task-id>([^<]+)</task-id>")
GIT = re.compile(r"(git|gh)\b")
BASH_RULES = (
    ("git/gh", GIT),
    ("python", re.compile(r"(python3?|uv run python)\b")),
    ("read-file", re.compile(r"(cat|sed|head|tail|nl|less|bat|jq|wc|awk)\b")),
    ("search", re.compile(r"(grep|rg|find|ls|fd|tree|ast-grep)\b")),
)
CODE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".sh", ".json", ".toml",
    ".yaml", ".yml", ".css", ".html", ".sql",
}  # fmt: skip
LINE_BUCKETS = (("<=20", 20), ("21-80", 80), (">80", 10**9))
FILE_KINDS = ("code", "docs markdown", "other markdown", "other")
THRESHOLDS = (3, 5, 8)
NOTIF_CAP = 3
DEFAULT_DAYS = 7
HUMAN, NOTIFICATION, RESULT, OTHER = "owner text", "notification turn", "tool result", "other"
NO_TEXT_PREFIXES = ("<local-command", "<command-name", "This session is being")
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

type Args = dict[str, object]


@dataclass
class Tool:
    """One tool call of a main call and the size of its result."""

    name: str
    args: Args
    ident: str
    chars: int = 0

    def kind(self) -> str:
        """Return the census class of this tool."""
        if self.name in SEARCH_TOOLS or self.name.startswith("mcp__fff__"):
            return "search"
        if self.name in {"Agent", "Task"}:
            return "Agent"
        if self.name == "MultiEdit":
            return "Edit"
        return self.name if self.name in {"Bash", "Read", "Edit", "Write", "Skill"} else "other"

    def is_lookup(self) -> bool:
        """Return whether this tool is a read-only lookup."""
        if self.name == "Bash":
            command = str(self.args.get("command", ""))
            return bash_class(command) in LOOKUP_BASH and not MUTATING.search(command)
        return self.name == "Read" or self.kind() == "search"


@dataclass
class Call:
    """One deduplicated main API response."""

    seg: int
    prices: tuple[float, float, float]
    cache_read: int
    output: int
    trigger: str
    notifs: int
    tools: list[Tool] = field(default_factory=lambda: cast("list[Tool]", []))
    both: bool = False  # pending input held tool results and a notification

    def read_usd(self) -> float:
        """Return the USD of the cache read of this call."""
        return self.cache_read * self.prices[2] / 1e6

    def output_usd(self) -> float:
        """Return the USD of the output of this call."""
        return self.output * self.prices[1] / 1e6

    def class_name(self) -> str:
        """Return the census class of this call."""
        if not self.tools:
            return "text-only"
        if len(self.tools) > 1:
            return "2+ tools"
        return "one tool: " + self.tools[0].kind()

    def result_chars(self) -> int:
        """Return the characters of all tool results of this call."""
        return sum(t.chars for t in self.tools)

    def is_lookup_call(self) -> bool:
        """Return whether every tool of this call is a read-only lookup."""
        return bool(self.tools) and all(t.is_lookup() for t in self.tools)

    def single(self, name: str) -> bool:
        """Return whether this call is exactly one tool call of the given name."""
        return len(self.tools) == 1 and self.tools[0].name == name


@dataclass
class Pending:
    """What reached the main since its previous call."""

    human: bool = False
    notifs: int = 0
    results: bool = False
    ids: set[str] = field(default_factory=lambda: cast("set[str]", set()))
    carried: set[str] = field(
        default_factory=lambda: cast("set[str]", set())
    )  # ids of the previous call

    def notify(self, text: str) -> None:
        """Count a notification once: it can arrive as a user record and as a queued command.

        An id already seen in this call or in the previous one is a repeat and counts nothing.
        """
        found = TASK_ID.search(text)
        if found is None:
            self.notifs += 1
            return
        ident = found.group(1)
        if ident not in self.ids and ident not in self.carried:
            self.notifs += 1
        self.ids.add(ident)

    def trigger(self) -> str:
        """Return the trigger class of the next call.

        A notification takes precedence over tool results: a call that answers both is a notification turn.
        """
        if self.human:
            return HUMAN
        if self.notifs:
            return NOTIFICATION
        return RESULT if self.results else OTHER


@dataclass
class Transcript:
    """Parsing state of one main transcript."""

    since: str
    calls: list[Call] = field(default_factory=lambda: cast("list[Call]", []))
    seen: dict[str, Call] = field(default_factory=lambda: cast("dict[str, Call]", {}))
    tools: dict[str, Tool] = field(default_factory=lambda: cast("dict[str, Tool]", {}))
    pending: Pending = field(default_factory=Pending)
    seg: int = 0


def bash_class(cmd: str) -> str:
    """Classify a Bash command like usage_main_context.py does."""
    text = re.sub(r"^\s*(cd [^&;]+(&&|;)\s*)+", "", cmd).strip()
    if CHECK.search(text.split("\n", 1)[0]) and not re.match(r"git\b", text):
        return "check"
    if MEM.search(text) and not GIT.match(text):
        return "mem"
    return next((name for name, rule in BASH_RULES if rule.match(text)), "other")


def family(model: object) -> str | None:
    """Return the price family of a model name."""
    name = str(model or "")
    return next((k for k in PRICE if k in name), None)


def price_of(fam: str, prompt_tokens: int) -> tuple[float, float, float]:
    """Return (input, output, cache read) USD per MTok for a call."""
    return HAIKU_LONG if fam == "haiku" and prompt_tokens > LONG_PROMPT else PRICE[fam]


def as_dict(value: object) -> dict[str, object]:
    """Return value when it is a dict, else an empty dict."""
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def as_int(value: object) -> int:
    """Return value when it is an int, else 0."""
    return value if isinstance(value, int) else 0


def flat(content: object) -> str:
    """Return the text of a tool result or message content, JSON for non-text blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in cast("list[object]", content):
        block = as_dict(item)
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif block and block.get("type") != "image":
            parts.append(json.dumps(block))
    return "".join(parts)


def new_call(state: Transcript, usage: dict[str, object], fam: str) -> Call:
    """Create a call from its first record and consume the pending trigger."""
    cache_read = as_int(usage.get("cache_read_input_tokens"))
    prompt = (
        as_int(usage.get("input_tokens"))
        + as_int(usage.get("cache_creation_input_tokens"))
        + cache_read
    )
    call = Call(
        state.seg,
        price_of(fam, prompt),
        cache_read,
        as_int(usage.get("output_tokens")),
        state.pending.trigger(),
        state.pending.notifs,
        both=state.pending.results and state.pending.notifs > 0,
    )
    state.pending = Pending(carried=state.pending.ids)
    state.calls.append(call)
    return call


def add_tools(state: Transcript, call: Call, content: object) -> None:
    """Attach the tool_use blocks of one streamed record to its call."""
    for item in cast("list[object]", content if isinstance(content, list) else []):
        block = as_dict(item)
        ident = str(block.get("id"))
        if block.get("type") != "tool_use" or ident in state.tools:
            continue
        tool = Tool(str(block.get("name")), as_dict(block.get("input")), ident)
        state.tools[ident] = tool
        call.tools.append(tool)


def on_assistant(state: Transcript, record: dict[str, object]) -> None:
    """Merge one assistant record into its deduplicated call."""
    message = as_dict(record.get("message"))
    usage = as_dict(message.get("usage"))
    fam = family(message.get("model"))
    mid = message.get("id")
    if not (isinstance(mid, str) and usage and fam):
        return
    call = state.seen.get(mid)
    if call is None:
        call = state.seen[mid] = new_call(state, usage, fam)
    call.output = max(call.output, as_int(usage.get("output_tokens")))
    add_tools(state, call, message.get("content"))


def is_human_text(record: dict[str, object], text: str) -> bool:
    """Return whether a user record is a prompt typed by the owner."""
    origin = as_dict(record.get("origin"))
    if origin:
        return origin.get("kind") == "human"
    if record.get("isMeta") or record.get("isCompactSummary"):
        return False
    return bool(text) and not text.startswith(("<", *NO_TEXT_PREFIXES))


def on_user(state: Transcript, record: dict[str, object]) -> None:
    """Record tool results and the kind of non-result user input."""
    content = as_dict(record.get("message")).get("content")
    blocks = [as_dict(b) for b in cast("list[object]", content) if isinstance(content, list)]
    results = [b for b in blocks if b.get("type") == "tool_result"]
    for block in results:
        tool = state.tools.get(str(block.get("tool_use_id")))
        if tool:
            tool.chars += len(flat(block.get("content")))
    if results:
        state.pending.results = True
        return
    text = flat(content)
    kind = as_dict(record.get("origin")).get("kind")
    if kind in {"task-notification", "peer"} or text.startswith("<task-notification>"):
        state.pending.notify(text)
    elif is_human_text(record, text):
        state.pending.human = True


def on_attachment(state: Transcript, record: dict[str, object]) -> None:
    """Count notifications and owner prompts delivered as queued commands."""
    att = as_dict(record.get("attachment"))
    if att.get("type") != "queued_command":
        return
    kind = as_dict(att.get("origin")).get("kind")
    if kind == "human":
        state.pending.human = True
    elif kind in {"task-notification", "peer"}:
        state.pending.notify(flat(att.get("prompt")) or flat(record.get("rendered")))


def on_record(state: Transcript, record: dict[str, object]) -> None:
    """Dispatch one transcript record."""
    kind = record.get("type")
    if kind == "system" and record.get("subtype") == "compact_boundary":
        state.seg += 1
        state.pending = Pending()
    elif kind == "assistant":
        on_assistant(state, record)
    elif kind == "user":
        on_user(state, record)
    elif kind == "attachment":
        on_attachment(state, record)


def parse(path: Path, since_iso: str) -> list[Call]:
    """Return the main calls of one transcript."""
    state = Transcript(since_iso)
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            try:
                record = as_dict(json.loads(line))
            except json.JSONDecodeError:
                continue
            if str(record.get("timestamp") or "") >= since_iso:
                on_record(state, record)
    return state.calls


def load(exclude: str, days: int) -> list[list[Call]]:
    """Return the calls of every main transcript changed within the window."""
    since = datetime.now(UTC) - timedelta(days=days)
    iso = since.strftime("%Y-%m-%dT%H:%M:%S")
    paths = [
        p
        for p in ROOT.glob("*/*.jsonl")
        if p.stat().st_mtime > since.timestamp() and exclude not in str(p)
    ]
    sessions = [parse(p, iso) for p in paths]
    return [s for s in sessions if s]


def table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    """Print a right-aligned table, first column left-aligned."""
    body = [[str(c) for c in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in body)) for i, h in enumerate(headers)]
    cells = [list(headers), *body]
    for row in cells:
        print(
            "  "
            + "  ".join(
                c.ljust(w) if i == 0 else c.rjust(w)
                for i, (c, w) in enumerate(zip(row, widths, strict=True))
            )
        )


def share(part: float, whole: float) -> str:
    """Format part of whole as a percentage."""
    return f"{100 * part / whole:.1f}%" if whole else "0.0%"


def tokens(chars: float) -> str:
    """Format an estimated token count."""
    return f"{chars / CHARS_PER_TOKEN / 1e3:,.0f}k"


def section_a(calls: list[Call]) -> None:
    """Print the call census."""
    print("\n## A. Call census (main calls by tool shape)")
    groups: defaultdict[str, list[Call]] = defaultdict(list)
    for call in calls:
        groups[call.class_name()].append(call)
    rows = [
        (
            name,
            len(g),
            share(len(g), len(calls)),
            f"{sum(c.read_usd() for c in g):.1f}",
            f"{sum(c.output_usd() for c in g):.1f}",
        )
        for name, g in sorted(groups.items(), key=lambda x: -len(x[1]))
    ]
    reads, outs = sum(c.read_usd() for c in calls), sum(c.output_usd() for c in calls)
    rows.append(("TOTAL", len(calls), "100.0%", f"{reads:.1f}", f"{outs:.1f}"))
    table(("class", "calls", "share", "cache-read USD", "output USD"), rows)


def section_b(calls: list[Call]) -> None:
    """Print the triggers of text-only calls and the notification-turn statistics."""
    print("\n## B. Triggers of text-only calls")
    text_only = [c for c in calls if not c.tools]
    rows = [
        (t, len(g), share(len(g), len(text_only)), f"{sum(c.read_usd() for c in g):.1f}")
        for t in (HUMAN, NOTIFICATION, RESULT, OTHER)
        if (g := [c for c in text_only if c.trigger == t])
    ]
    table(("trigger", "calls", "share", "cache-read USD"), rows)
    notif = [c for c in calls if c.trigger == NOTIFICATION]
    with_tools = sum(1 for c in notif if c.tools)
    print(
        f"\n  notification turns (any call): {len(notif)}, cache-read USD {sum(c.read_usd() for c in notif):.1f}"
    )
    print(f"  with at least one tool call: {with_tools}, none: {len(notif) - with_tools}")
    both = sum(1 for c in text_only if c.both)
    print(
        f"  text-only calls with tool results and a notification (counted as notification turn): {both}"
    )
    dist = Counter(min(c.notifs, NOTIF_CAP) for c in notif)
    print(
        "  notifications per trigger: "
        + ", ".join(f"{'3+' if k == NOTIF_CAP else k}: {dist[k]}" for k in range(1, NOTIF_CAP + 1))
    )


def lookup_runs(session: list[Call]) -> list[list[Call]]:
    """Split one session into maximal runs of read-only lookup calls."""
    runs: list[list[Call]] = []
    run: list[Call] = []
    for call in session:
        starts_new = call.trigger == HUMAN or (run and run[-1].seg != call.seg)
        if starts_new and run:
            runs.append(run)
            run = []
        if call.is_lookup_call():
            run.append(call)
        elif run:
            runs.append(run)
            run = []
    return [*runs, run] if run else runs


def section_c(sessions: list[list[Call]]) -> None:
    """Print inline lookup runs."""
    print(
        "\n## C. Inline lookup runs (Read, search, Bash read-file/search/git/mem; no owner prompt inside)"
    )
    runs = [r for s in sessions for r in lookup_runs(s)]
    lengths = [len(r) for r in runs]
    rows = []
    for limit in THRESHOLDS:
        sel = [r for r in runs if len(r) >= limit]
        calls = [c for r in sel for c in r]
        rows.append((
            f">= {limit}",
            len(sel),
            len(calls),
            tokens(sum(c.result_chars() for c in calls)),
            f"{sum(c.read_usd() for c in calls):.1f}",
        ))
    table(("run length", "runs", "calls", "est. result tokens", "cache-read USD"), rows)
    ordered = sorted(lengths)
    p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))] if ordered else 0
    print(
        f"  all lookup runs {len(runs)}: median {statistics.median(lengths) if lengths else 0}, p90 {p90}, max {max(lengths, default=0)}"
    )


def line_bucket(lines: int) -> str:
    """Return the line-count bucket label."""
    return next(label for label, top in LINE_BUCKETS if lines <= top)


def file_kind(path: str) -> str:
    """Return the file kind of an edited path."""
    suffix = Path(path).suffix.lower()
    if suffix in {".md", ".mdx"}:
        lowered = path.lower()
        is_doc = (
            "/docs/" in lowered
            or lowered.startswith("docs/")
            or "plan" in lowered
            or "adr" in lowered
        )
        return FILE_KINDS[1] if is_doc else FILE_KINDS[2]
    return FILE_KINDS[0] if suffix in CODE_EXT else FILE_KINDS[3]


def written_text(tool: Tool) -> str:
    """Return the text an Edit or Write call puts into a file."""
    args = tool.args
    if tool.name == "Write":
        return str(args.get("content", ""))
    if tool.name == "MultiEdit":
        edits = cast(
            "list[object]", args.get("edits") if isinstance(args.get("edits"), list) else []
        )
        return "\n".join(str(as_dict(e).get("new_string", "")) for e in edits)
    return str(args.get("new_string", ""))


def section_d(calls: list[Call]) -> None:
    """Print inline writes by size and file kind."""
    print("\n## D. Inline writes (Edit/Write/MultiEdit of the main): calls / chars per cell")
    cells: defaultdict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for call in calls:
        for tool in call.tools:
            if tool.name not in {"Edit", "Write", "MultiEdit"}:
                continue
            text = written_text(tool)
            cell = cells[
                line_bucket(text.count("\n") + 1 if text else 0),
                file_kind(str(tool.args.get("file_path", ""))),
            ]
            cell[0] += 1
            cell[1] += len(text)
    rows = [
        (label, *(f"{cells[label, k][0]} / {cells[label, k][1]:,}" for k in FILE_KINDS))
        for label, _ in LINE_BUCKETS
    ]
    table(("lines written", *FILE_KINDS), rows)


def track_read(tool: Tool, read: set[str], found: list[int]) -> None:
    """Update the paths read in a segment and collect a repeated Read."""
    path = str(tool.args.get("file_path", ""))
    if tool.name in WRITE_TOOLS:
        read.discard(path)
    elif tool.name == "Read":
        if path in read:
            found.append(tool.chars)
        read.add(path)


def repeated_reads(session: list[Call]) -> list[int]:
    """Return the result chars of each Read repeating a path already read in its segment."""
    found: list[int] = []
    read: set[str] = set()
    seg = 0
    for call in session:
        if call.seg != seg:
            seg, read = call.seg, set()
        for tool in call.tools:
            track_read(tool, read, found)
    return found


def section_e(sessions: list[list[Call]]) -> None:
    """Print repeated reads."""
    print(
        "\n## E. Repeated reads (same path, same segment, no Edit/Write to it in between; offsets ignored)"
    )
    found = [n for s in sessions for n in repeated_reads(s)]
    total_reads = sum(1 for s in sessions for c in s for t in c.tools if t.name == "Read")
    print(
        f"  repeated Read calls {len(found)} of {total_reads} Read calls ({share(len(found), total_reads)}), est. tokens of their results {tokens(sum(found))}"
    )


def bash_runs(session: list[Call], minimum: int = THRESHOLDS[0]) -> list[list[Call]]:
    """Return the runs of at least `minimum` consecutive calls that are each exactly one Bash call."""
    runs: list[list[Call]] = []
    run: list[Call] = []
    for call in [*session, Call(0, (0, 0, 0), 0, 0, OTHER, 0)]:
        if call.single("Bash"):
            run.append(call)
            continue
        if len(run) >= minimum:
            runs.append(run)
        run = []
    return runs


def percentile(ordered: list[int], fraction: float) -> int:
    """Return the nearest-rank percentile of an ascending list, or 0 for none."""
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))] if ordered else 0


def shell_run_figures(sessions: list[list[Call]]) -> None:
    """Print the length percentiles of the single-shell runs and the command classes inside runs of 3+."""
    for minimum in (1, THRESHOLDS[0]):
        lengths = sorted(len(r) for s in sessions for r in bash_runs(s, minimum))
        print(
            f"  single-Bash runs of {minimum}+: {len(lengths)}, length p50 {percentile(lengths, 0.5)}, "
            f"p90 {percentile(lengths, 0.9)}, p99 {percentile(lengths, 0.99)}, max {max(lengths, default=0)}"
        )
    classes = Counter(
        bash_class(str(c.tools[0].args.get("command", "")))
        for s in sessions
        for r in bash_runs(s)
        for c in r
    )
    total = sum(classes.values())
    print(
        "  calls inside runs of 3+ by command class: "
        + ", ".join(f"{name} {n} ({share(n, total)})" for name, n in classes.most_common())
    )


def section_f(sessions: list[list[Call]]) -> None:
    """Print parallelism figures."""
    print("\n## F. Parallelism")
    calls = [c for s in sessions for c in s]
    tool_calls = [c for c in calls if c.tools]
    one_bash = sum(1 for c in calls if c.single("Bash"))
    runs = [len(r) for s in sessions for r in bash_runs(s)]
    print(
        f"  tool-using calls with 2+ tool calls: {sum(1 for c in tool_calls if len(c.tools) > 1)} of {len(tool_calls)} ({share(sum(1 for c in tool_calls if len(c.tools) > 1), len(tool_calls))})"
    )
    print(
        f"  calls that are exactly one Bash call: {one_bash} of {len(calls)} ({share(one_bash, len(calls))})"
    )
    print(
        f"  runs of 3+ consecutive single-Bash calls: {len(runs)}, calls inside them: {sum(runs)}"
    )
    shell_run_figures(sessions)


def main() -> None:
    """Run every section over the window."""
    args = sys.argv[1:]
    exclude = args[0] if args else "\0"
    days = int(args[1]) if len(args) > 1 else DEFAULT_DAYS
    started = time.time()
    sessions = load(exclude, days)
    calls = [c for s in sessions for c in s]
    print(
        f"main sessions {len(sessions)}  main calls {len(calls)}  window {days} days  chars/token {CHARS_PER_TOKEN}"
    )
    section_a(calls)
    section_b(calls)
    section_c(sessions)
    section_d(calls)
    section_e(sessions)
    section_f(sessions)
    print(f"\n(elapsed {time.time() - started:.0f}s)")


if __name__ == "__main__":
    main()
