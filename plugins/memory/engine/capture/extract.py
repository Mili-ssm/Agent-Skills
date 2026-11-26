"""Reduce a Claude Code session transcript to a compact extract and validate
the memory candidates a model proposes from it.

Pure; standard library and `records` only. The transcript is read line by line and the
extract is bounded while reading, because transcripts reach hundreds of
megabytes. Who is the owner is decided by `origin.kind`, not by the entry
type: most string user entries are subagent reports.
"""

import json
import logging
import re
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from store import records

logger = logging.getLogger(__name__)

SIGNALS: tuple[str, ...] = (
    "owner_correction",
    "failed_then_passed",
    "verified_review_finding",
    "plan_changed_by_review",
    "delegation_failed",
    "rework",
    "repeated_tool_error",
    "decision_with_reason",
    "owner_approval",
    "owner_request_paid_off",
    "effective_practice",
)
# What a signal says about the lesson (C65): a failure, a thing that worked, or only that it was seen.
_FAILED = (
    "owner_correction",
    "failed_then_passed",
    "verified_review_finding",
    "delegation_failed",
    "rework",
    "repeated_tool_error",
)
_WORKED = ("owner_approval", "owner_request_paid_off", "effective_practice")


def outcome(signal: str) -> str:
    """The case outcome a capture signal records; an unknown signal is `seen`."""
    return "failed" if signal in _FAILED else "worked" if signal in _WORKED else "seen"


REACHES = records.REACHES
FORMS: tuple[str, ...] = ("suggestion", "recommendation")
SAME_AS_MIN = 0.3  # the larger share of one claim's terms found in the other, in either direction
KINDS: tuple[str, ...] = ("lesson", "pitfall", "decision")
EXTRACT_LIMIT = 80_000
PART_SIZE = 40_000
MAX_CANDIDATES = 5
CLAIM_MIN = 20
CLAIM_MAX = 400
EVIDENCE_MIN = 15
CONTEXT_LIMIT = 300

_HUMAN_LIMIT = 2000  # an owner's words are kept longer than a subagent report
_REPORT_LIMIT = 800
_AGENT_LIMIT = 1500
_ARG_LIMIT = 200
_ERROR_LIMIT = 400
_TOOL_ARGS = ("command", "file_path", "description")
_OWNER_SIGNALS = (
    "owner_correction",
    "decision_with_reason",
    "owner_approval",
    "owner_request_paid_off",
)
_LINE_KINDS = ("OWNER", "OWNER ANSWER", "REPORT", "AGENT", "TOOL", "TOOL ERROR", "TOOL OK")
_MARKER = "[...] earlier lines left out"
LEFT_OUT_MARKER = _MARKER
last_skipped = 0  # lines the last extract() could not process, for the caller to report
last_more = False  # forward mode: lines remain after the window the last extract() returned
_KIND_RE = re.compile(r"^\[\d+\] (OWNER ANSWER|OWNER|REPORT|AGENT|TOOL ERROR|TOOL OK|TOOL)\b")
_BODY_RE = re.compile(r"^\[\d+\] (OWNER ANSWER|OWNER|REPORT|AGENT|TOOL ERROR \S+|TOOL \S+): (.*)$")


def _flat(text: str, limit: int) -> str:
    # cut before normalizing so memory does not follow the size of the line; a text that is mostly
    # whitespace can come out shorter than `limit` with its tail lost, which is accepted
    return " ".join(text[: limit * 8].split())[:limit].strip()


def _text_of(content: object) -> str:
    """Text of a string or of the text blocks of a list; "" otherwise."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif (
                isinstance(b, dict)
                and b.get("type", "text") == "text"
                and isinstance(b.get("text"), str)
            ):
                parts.append(b["text"])
        return " ".join(parts)
    return ""


def _blocks(content: object) -> list[dict]:
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _name(value: object) -> str:
    return value if isinstance(value, str) and value else "?"


def _is_human(origin: object) -> bool:
    return isinstance(origin, dict) and origin.get("kind") == "human"


def _queued_prompt(entry: dict) -> dict | None:
    att = entry.get("attachment")
    if (
        isinstance(att, dict)
        and att.get("type") == "queued_command"
        and att.get("commandMode") == "prompt"
        and not att.get("isMeta")
        and not entry.get("isMeta")
    ):
        return att
    return None


def _attachment_events(entry: dict) -> list[str]:
    att = _queued_prompt(entry)
    if att is None:
        return []
    origin = att.get(
        "origin", entry.get("origin")
    )  # the origin of a queued command sits on the attachment
    human = origin is None or _is_human(origin)
    text = _flat(_text_of(att.get("prompt")), _HUMAN_LIMIT if human else _REPORT_LIMIT)
    if not text:
        return []
    return [f"OWNER: {text}" if human else f"REPORT: {text}"]


def _tool_arg(inp: object) -> str:
    if not isinstance(inp, dict):
        return ""
    for key in _TOOL_ARGS:
        value = inp.get(key)
        if isinstance(value, str):
            return value
    return ""


def _tool_use_line(b: dict, names: dict) -> str:
    name = _name(b.get("name"))
    if isinstance(b.get("id"), str):
        names[b["id"]] = name
    return f"TOOL {name}: {_flat(_tool_arg(b.get('input')), _ARG_LIMIT)}"


def _assistant_events(content: object, names: dict) -> list[str]:
    out: list[str] = []
    blocks: list[dict] = (
        [{"type": "text", "text": content}] if isinstance(content, str) else _blocks(content)
    )
    for b in blocks:
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            text = _flat(b["text"], _AGENT_LIMIT)
            if text:
                out.append(f"AGENT: {text}")
        elif b.get("type") == "tool_use":
            out.append(_tool_use_line(b, names))
    return out


def _result_event(b: dict, name: str, state: dict) -> str | None:
    if b.get("is_error"):
        state[name] = True
        return f"TOOL ERROR {name}: {_flat(_text_of(b.get('content')), _ERROR_LIMIT)}"
    was_failing = state.get(name)
    state[name] = False
    if name == "AskUserQuestion":
        return f"OWNER ANSWER: {_flat(_text_of(b.get('content')), _REPORT_LIMIT)}"
    return f"TOOL OK {name}" if was_failing else None


def _result_events(content: object, names: dict, state: dict) -> list[str]:
    out: list[str] = []
    for b in _blocks(content):
        if b.get("type") != "tool_result":
            continue
        event = _result_event(b, names.get(b.get("tool_use_id"), "?"), state)
        if event is not None:
            out.append(event)
    return out


def _user_text_events(entry: dict, content: object) -> list[str]:
    if entry.get("isMeta") or entry.get("isCompactSummary"):
        return []
    text = _text_of(content)
    if not text.strip():
        return []
    origin = entry.get("origin")
    human = _is_human(origin) or (origin is None and not text.lstrip().startswith("<"))
    body = _flat(text, _HUMAN_LIMIT if human else _REPORT_LIMIT)
    if body and human:
        return [f"OWNER: {body}"]
    if body and origin is not None:
        return [f"REPORT: {body}"]
    return []


def _events(entry: dict, names: dict, state: dict) -> list[str]:
    """Extract lines (without the line number prefix) of one transcript entry."""
    kind = entry.get("type")
    if kind == "attachment":
        return _attachment_events(entry)
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if kind == "assistant":
        return _assistant_events(content, names)
    if kind != "user":
        return []
    return _result_events(content, names, state) + _user_text_events(entry, content)


def _decode(raw: str, names: dict, state: dict) -> list[str]:
    entry = json.loads(raw)
    return _events(entry, names, state) if isinstance(entry, dict) else []


class _Window:
    """The kept lines of an extract, bounded to the budget."""

    def __init__(self, forward: bool) -> None:
        self.forward = forward
        self.budget = EXTRACT_LIMIT - len(_MARKER) - 1
        self.lines: deque[str] = deque()
        self.size = 0  # characters of the kept lines, one newline each
        self.left_out = False

    def overflows(self, n: int, events: list[str]) -> bool:
        if not (self.forward and self.lines):
            return False
        return self.size + sum(len(f"[{n}] {ev}") + 1 for ev in events) > self.budget

    def add(self, n: int, events: list[str]) -> None:
        for ev in events:
            line = f"[{n}] {ev}"
            self.lines.append(line)
            self.size += len(line) + 1
            while not self.forward and self.size > self.budget and self.lines:
                self.size -= len(self.lines.popleft()) + 1
                self.left_out = True

    def text(self) -> str:
        if self.left_out:
            self.lines.appendleft(_MARKER)
        return "\n".join(self.lines)


class _Scan:
    """One pass over a transcript: the window plus what `extract` reports about it."""

    def __init__(self, since_line: int, forward: bool) -> None:
        self.forward = forward
        self.window = _Window(forward)
        self.names: dict = {}
        self.state: dict = {}
        self.last = since_line
        self.skipped = 0
        self.more = False

    def prime(self, raw: str) -> None:
        """Learn tool names and failure state from a line before the window; nothing else matters."""
        if "tool_use" not in raw and "tool_result" not in raw:
            return
        try:
            _decode(raw, self.names, self.state)
        except Exception:
            # not counted: the earlier window already reported it
            logger.debug("capture: unreadable line before the window", exc_info=True)

    def read(self, n: int, raw: str) -> bool:
        """Take line `n` into the window; False when the window is done."""
        if self.forward and not raw.endswith("\n"):
            return False  # a line still being written is read once it is finished
        self.last = n
        try:  # no line of any content may stop the extract
            events = _decode(raw, self.names, self.state)
        except json.JSONDecodeError:
            return True  # a line that is not JSON is ordinary
        except Exception:
            # anything else may be a defect here: counted, so an emptied extract is noticed
            logger.debug("capture: line %d could not be processed", n, exc_info=True)
            self.skipped += 1
            return True
        if self.window.overflows(n, events):
            self.last, self.more = n - 1, True
            return False
        self.window.add(n, events)
        return True


def extract(transcript: Path, since_line: int = 0, forward: bool = False) -> tuple[str, int]:
    """Extract text and number of the last line read (1-based).

    By default the newest lines are kept and the oldest left out. With `forward` the window starts at
    `since_line` and stops before the first line that would overflow it (`last_more` is then True); a first
    line larger than the budget is kept, so every call advances, and an unterminated last line is left for the
    next call. Lines up to `since_line` are parsed only to know the tool names and failures a result refers to."""
    scan = _Scan(since_line, forward)
    with open(transcript, encoding="utf-8", errors="replace") as f:
        for n, raw in enumerate(f, 1):
            if n <= since_line:
                scan.prime(raw)
            elif not scan.read(n, raw):
                break
    global last_skipped, last_more
    last_skipped, last_more = scan.skipped, scan.more
    return scan.window.text(), scan.last


def parts(text: str, size: int = PART_SIZE) -> list[str]:
    """Split at line boundaries into pieces of at most `size` characters."""
    pieces: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in text.split("\n"):
        if cur and cur_len + 1 + len(line) > size:
            pieces.append("\n".join(cur))
            cur, cur_len = [], 0
        cur_len += len(line) + (1 if cur else 0)
        cur.append(line)
    pieces.append("\n".join(cur))
    return pieces


def counts(extract_text: str) -> dict[str, int]:
    result: dict[str, int] = dict.fromkeys(_LINE_KINDS, 0)
    for line in extract_text.split("\n"):
        m = _KIND_RE.match(line)
        if m:
            result[m.group(1)] += 1
    return result


def _squash(s: str) -> str:
    return " ".join(s.split())


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


_ENUM_FIELDS = (
    ("kind", None, KINDS),
    ("signal", None, SIGNALS),
    ("reach", "project", REACHES),
    ("weight", "medium", records.WEIGHTS),
    ("form", "recommendation", FORMS),
)


def _field_reason(item: dict) -> str:
    for key, default, allowed in _ENUM_FIELDS:
        if item.get(key, default) not in allowed:
            return key
    if item["kind"] == "decision" and item.get("reach", "project") == "general":
        return "a decision is a project record"
    return ""


def _link_reason(item: dict, handles: Mapping[str, str]) -> str:
    same_as = item.get("same_as")
    if same_as is not None and (not isinstance(same_as, str) or same_as not in handles):
        return "same_as"
    claim = item.get("claim")
    if not isinstance(claim, str) or not CLAIM_MIN <= len(_squash(claim)) <= CLAIM_MAX:
        return "claim length"
    if same_as is not None and _overlap(claim, handles[same_as]) < SAME_AS_MIN:
        return "same_as mismatch"
    return ""


def _evidence_reason(item: dict, bodies: list[tuple[str, str]]) -> str:
    evidence = item.get("evidence")
    ev = " ".join(evidence.split()) if isinstance(evidence, str) else ""
    hits = [k for k, body in bodies if ev in body] if len(ev) >= EVIDENCE_MIN else []
    if not hits:
        return "evidence not in the transcript"
    if item["signal"] in _OWNER_SIGNALS and not any(k.startswith("OWNER") for k in hits):
        return "evidence is not the owner's words"
    return ""


def _repeat_reason(item: dict, recorded: set[str], sighted: set[str]) -> str:
    same_as = item.get("same_as")
    if same_as is not None:
        return "same_as repeated" if same_as in sighted else ""
    return "already recorded" if _norm(item["claim"]) in recorded else ""


def _reason(
    item: object,
    bodies: list[tuple[str, str]],
    recorded: set[str],
    handles: Mapping[str, str],
    sighted: set[str],
) -> str:
    if not isinstance(item, dict):
        return "not an object"
    return (
        _field_reason(item)
        or _link_reason(item, handles)
        or _evidence_reason(item, bodies)
        or _repeat_reason(item, recorded, sighted)
    )


def _overlap(claim: str, other: str) -> float:
    """How much two claims share, from either side: a hedged candidate is longer than the record it repeats."""
    a, b = records.tokenize(claim), records.tokenize(other)
    return max(records.containment(a, set(b)), records.containment(b, set(a)))


def _bodies(extract_text: str) -> list[tuple[str, str]]:
    bodies = []
    for line in extract_text.split("\n"):
        m = _BODY_RE.match(line)
        if m:
            bodies.append((m.group(1), " ".join(m.group(2).split())))
    return bodies


def _by_claim(handles: Mapping[str, str]) -> dict[str, str]:
    by_claim: dict[str, str] = {}
    for h, c in handles.items():
        # the same claim in a project record and a global one links to the global one: sightings are counted there
        if _norm(c) not in by_claim or h.startswith("g:"):
            by_claim[_norm(c)] = h
    return by_claim


def _link_identical(item: Any, by_claim: Mapping[str, str]) -> Any:
    """An identical claim is one more sighting of the project's record, not a new one."""
    if (
        isinstance(item, dict)
        and item.get("same_as") is None
        and isinstance(item.get("claim"), str)
        and _norm(item["claim"]) in by_claim
    ):
        return {**item, "same_as": by_claim[_norm(item["claim"])]}
    return item


def _kept_entry(item: dict) -> dict:
    context = item.get("context")
    return {
        "kind": item["kind"],
        "signal": item["signal"],
        "reach": item.get("reach", "project"),
        "weight": item.get("weight", "medium"),
        "form": item.get("form", "recommendation"),
        "claim": _squash(item["claim"]),
        "context": _squash(context)[:CONTEXT_LIMIT] if isinstance(context, str) else "",
        "evidence": _squash(item["evidence"]),
        "same_as": item.get("same_as"),
    }


def validate(
    candidates: object, extract_text: str, recorded: Sequence[str], handles: Mapping[str, str] = {}
) -> tuple[list[dict], list[dict]]:
    """Split candidates into kept and dropped ({"candidate", "reason"}). `handles` maps "m:<handle>" to the claim
    of a memory of this project that a candidate may name in `same_as` as one more sighting."""
    if not isinstance(candidates, list):
        return [], [{"candidate": candidates, "reason": "not a list"}]
    bodies = _bodies(extract_text)
    done = {_norm(r) for r in recorded}
    by_claim = _by_claim(handles)
    kept: list[dict] = []
    dropped: list[dict] = []
    sighted: set[str] = set()
    for candidate in candidates:
        item = _link_identical(candidate, by_claim)
        over = len(kept) >= MAX_CANDIDATES
        reason = "over the limit" if over else _reason(item, bodies, done, handles, sighted)
        if reason:
            dropped.append({"candidate": item, "reason": reason})
            continue
        if item.get("same_as") is not None:
            sighted.add(item["same_as"])
        kept.append(_kept_entry(item))
    return kept, dropped
