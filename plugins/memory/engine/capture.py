"""Reduce a Claude Code session transcript to a compact extract and validate
the memory candidates a model proposes from it.

Pure; standard library plus the engine's own modules. The transcript is read line by line and the
extract is bounded while reading, because transcripts reach hundreds of
megabytes. Who is the owner is decided by `origin.kind`, not by the entry
type: most string user entries are subagent reports.
"""
import json
import re
from collections import deque
from pathlib import Path
from typing import Mapping, Sequence

import mem
import records

SIGNALS: tuple[str, ...] = ("owner_correction", "failed_then_passed", "verified_review_finding", "plan_changed_by_review",
                            "delegation_failed", "rework", "repeated_tool_error", "decision_with_reason")
REACHES = records.REACHES
FORMS: tuple[str, ...] = ("suggestion", "recommendation")
SAME_AS_MIN = 0.3  # share of the candidate's claim terms found in the claim it says it repeats
KINDS: tuple[str, ...] = ("lesson", "pitfall", "decision")
EXTRACT_LIMIT = 80_000
PART_SIZE = 40_000
MAX_CANDIDATES = 5

_OWNER_SIGNALS = ("owner_correction", "decision_with_reason")
_LINE_KINDS = ("OWNER", "OWNER ANSWER", "REPORT", "AGENT", "TOOL", "TOOL ERROR", "TOOL OK")
_MARKER = "[...] earlier lines left out"
LEFT_OUT_MARKER = _MARKER
last_skipped = 0  # lines the last extract() could not process, for the caller to report
_KIND_RE = re.compile(r"^\[\d+\] (OWNER ANSWER|OWNER|REPORT|AGENT|TOOL ERROR|TOOL OK|TOOL)\b")
_BODY_RE = re.compile(r"^\[\d+\] (OWNER ANSWER|OWNER|REPORT|AGENT|TOOL ERROR \S+|TOOL \S+): (.*)$")


def _flat(text: str, limit: int) -> str:
    # cut before normalizing so memory does not follow the size of the line; a text that is mostly
    # whitespace can come out shorter than `limit` with its tail lost, which is accepted
    return " ".join(text[:limit * 8].split())[:limit].strip()


def _text_of(content: object) -> str:
    """Text of a string or of the text blocks of a list; "" otherwise."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type", "text") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
        return " ".join(parts)
    return ""


def _blocks(content: object) -> list[dict]:
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _name(value: object) -> str:
    return value if isinstance(value, str) and value else "?"


def _events(entry: dict, names: dict, state: dict) -> list[str]:
    """Extract lines (without the line number prefix) of one transcript entry."""
    kind = entry.get("type")
    out: list[str] = []
    if kind == "attachment":
        att = entry.get("attachment")
        if (isinstance(att, dict) and att.get("type") == "queued_command" and att.get("commandMode") == "prompt"
                and not att.get("isMeta") and not entry.get("isMeta")):
            origin = att.get("origin", entry.get("origin"))  # the origin of a queued command sits on the attachment
            human = origin is None or (isinstance(origin, dict) and origin.get("kind") == "human")
            text = _flat(_text_of(att.get("prompt")), 2000 if human else 800)
            if text:
                out.append(f"OWNER: {text}" if human else f"REPORT: {text}")
        return out
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if kind == "assistant":
        for b in ([{"type": "text", "text": content}] if isinstance(content, str) else _blocks(content)):
            if b.get("type") == "text" and isinstance(b.get("text"), str):
                text = _flat(b["text"], 1500)
                if text:
                    out.append(f"AGENT: {text}")
            elif b.get("type") == "tool_use":
                name = _name(b.get("name"))
                if isinstance(b.get("id"), str):
                    names[b["id"]] = name
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                arg = next((inp[k] for k in ("command", "file_path", "description") if isinstance(inp.get(k), str)), "")
                out.append(f"TOOL {name}: {_flat(arg, 200)}")
        return out
    if kind != "user":
        return out
    for b in _blocks(content):
        if b.get("type") != "tool_result":
            continue
        name = names.get(b.get("tool_use_id"), "?")
        if b.get("is_error"):
            state[name] = True
            out.append(f"TOOL ERROR {name}: {_flat(_text_of(b.get('content')), 400)}")
        else:
            if name == "AskUserQuestion":
                out.append(f"OWNER ANSWER: {_flat(_text_of(b.get('content')), 800)}")
            elif state.get(name):
                out.append(f"TOOL OK {name}")
            state[name] = False
    if entry.get("isMeta") or entry.get("isCompactSummary"):
        return out
    text = _text_of(content)
    if not text.strip():
        return out
    origin = entry.get("origin")
    human = (isinstance(origin, dict) and origin.get("kind") == "human") or (origin is None and not text.lstrip().startswith("<"))
    body = _flat(text, 2000 if human else 800)
    if body and human:
        out.append(f"OWNER: {body}")
    elif body and origin is not None:
        out.append(f"REPORT: {body}")
    return out


def extract(transcript: Path, since_line: int = 0) -> tuple[str, int]:
    """Extract text and number of the last line read (1-based)."""
    budget = EXTRACT_LIMIT - len(_MARKER) - 1
    lines: deque[str] = deque()
    size = 0  # characters of the kept lines, one newline each
    left_out = False
    names: dict = {}
    state: dict = {}
    last = since_line
    skipped = 0
    with open(transcript, encoding="utf-8", errors="replace") as f:
        for n, raw in enumerate(f, 1):
            if n <= since_line:
                continue
            last = n
            try:  # no line of any content may stop the extract
                entry = json.loads(raw)
                events = _events(entry, names, state) if isinstance(entry, dict) else []
            except json.JSONDecodeError:
                continue  # a line that is not JSON is ordinary
            except Exception:
                skipped += 1  # anything else may be a defect here: counted, so an emptied extract is noticed
                continue
            for ev in events:
                line = f"[{n}] {ev}"
                lines.append(line)
                size += len(line) + 1
                while size > budget and lines:
                    size -= len(lines.popleft()) + 1
                    left_out = True
    if left_out:
        lines.appendleft(_MARKER)
    global last_skipped
    last_skipped = skipped
    return "\n".join(lines), last


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
    result = {k: 0 for k in _LINE_KINDS}
    for line in extract_text.split("\n"):
        m = _KIND_RE.match(line)
        if m:
            result[m.group(1)] += 1
    return result


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def _reason(item: object, bodies: list[tuple[str, str]], recorded: set[str], handles: Mapping[str, str],
            sighted: set[str]) -> str:
    if not isinstance(item, dict):
        return "not an object"
    if item.get("kind") not in KINDS:
        return "kind"
    if item.get("signal") not in SIGNALS:
        return "signal"
    if item.get("reach", "project") not in REACHES:
        return "reach"
    if item.get("weight", "medium") not in records.WEIGHTS:
        return "weight"
    if item.get("form", "recommendation") not in FORMS:
        return "form"
    if item["kind"] == "decision" and item.get("reach", "project") == "general":
        return "a decision is a project record"
    same_as = item.get("same_as")
    if same_as is not None and (not isinstance(same_as, str) or same_as not in handles):
        return "same_as"
    claim = item.get("claim")
    if not isinstance(claim, str) or not 20 <= len(claim) <= 300:
        return "claim length"
    if same_as is not None and records.containment(mem.tokenize(claim), set(mem.tokenize(handles[same_as]))) < SAME_AS_MIN:
        return "same_as mismatch"
    evidence = item.get("evidence")
    ev = " ".join(evidence.split()) if isinstance(evidence, str) else ""
    hits = [k for k, body in bodies if ev in body] if len(ev) >= 15 else []
    if not hits:
        return "evidence not in the transcript"
    if item["signal"] in _OWNER_SIGNALS and not any(k.startswith("OWNER") for k in hits):
        return "evidence is not the owner's words"
    if same_as is not None:
        if same_as in sighted:
            return "same_as repeated"
    elif _norm(claim) in recorded:
        return "already recorded"
    return ""


def validate(candidates: object, extract_text: str, recorded: Sequence[str],
             handles: Mapping[str, str] = {}) -> tuple[list[dict], list[dict]]:
    """Split candidates into kept and dropped ({"candidate", "reason"}). `handles` maps "m:<handle>" to the claim
    of a memory of this project that a candidate may name in `same_as` as one more sighting."""
    if not isinstance(candidates, list):
        return [], [{"candidate": candidates, "reason": "not a list"}]
    bodies = []
    for line in extract_text.split("\n"):
        m = _BODY_RE.match(line)
        if m:
            bodies.append((m.group(1), " ".join(m.group(2).split())))
    done = {_norm(r) for r in recorded}
    kept: list[dict] = []
    dropped: list[dict] = []
    sighted: set[str] = set()
    for item in candidates:
        reason = "over the limit" if len(kept) >= MAX_CANDIDATES else _reason(item, bodies, done, handles, sighted)
        if reason:
            dropped.append({"candidate": item, "reason": reason})
        else:
            context = item.get("context")
            same_as = item.get("same_as")
            if same_as is not None:
                sighted.add(same_as)
            kept.append({"kind": item["kind"], "signal": item["signal"], "reach": item.get("reach", "project"),
                         "weight": item.get("weight", "medium"), "form": item.get("form", "recommendation"),
                         "claim": item["claim"], "context": context if isinstance(context, str) else "",
                         "evidence": item["evidence"], "same_as": same_as})
    return kept, dropped
