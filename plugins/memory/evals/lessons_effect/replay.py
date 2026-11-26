#!/usr/bin/env python3
"""Replay of real failures, part A: everything that needs no model (see README.md, "Replay of real failures").

A real transcript is copied up to the entry just before a known failing assistant message; part B resumes the
copy headless in two arms and scores the next message. This file builds the copy, the arm files, the worktree and
the per-point checks, and scores a message by code.

Usage: replay.py check POINTS_FILE [--max-context N] | replay.py --self-check
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trial_env
from rules_layout.run_trial import write_settings

REPO = trial_env.REPO
BASE = REPO / "target" / "lessons-replay"
PROJECTS = Path.home() / ".claude" / "projects"
PROMPT = "Continue."
BLOCK_PHRASE = "lessons learned in earlier sessions"
DEFAULT_MAX_CONTEXT = 900_000
EXIT_PROBLEMS = 2
DENY_OUTPUT = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "replay: tools are not run",
    }
}
RULE_FIELDS = ("tool", "command", "text", "input")
POINT_STRINGS = ("name", "transcript", "lesson_line", "question")
USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


@dataclass
class Message:
    """What the scorer sees: the text blocks and the tool calls (`{"name", "input"}`) of one assistant message."""

    text: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Point:
    name: str
    transcript: Path
    cut_line: int
    markers: list[str]
    lesson_line: str
    topic: str | None
    question: str
    rule: dict[str, Any]
    compliant: Message
    commit: str | None = None


@dataclass
class Copy:
    session_id: str
    path: Path
    work: Path
    prompt: str
    context_tokens: int
    cut_timestamp: str
    first: int  # index of the first entry of the failing message


# --- points file ---------------------------------------------------------------------------------------------


def _check_pattern(item: Any) -> str | None:
    if not (
        isinstance(item, dict)
        and item.get("field") in RULE_FIELDS
        and isinstance(item.get("regex"), str)
    ):
        return f"rule: each pattern needs a field in {RULE_FIELDS} and a regex string"
    try:
        re.compile(item["regex"])
    except re.error as err:
        return f"rule: bad regex ({err})"
    return None


def _check_rule(rule: Any) -> str | None:
    """The problem with a rule, or None."""
    if not isinstance(rule, dict) or rule.get("kind") not in {"judge", "code"}:
        return "rule: kind must be 'judge' or 'code'"
    if rule["kind"] == "judge":
        return None
    patterns = rule.get("patterns")
    if rule.get("pass_when") not in {"any", "none"}:
        return "rule: pass_when must be 'any' or 'none'"
    if not isinstance(patterns, list) or not patterns:
        return "rule: patterns must be a non-empty list"
    return next(filter(None, map(_check_pattern, patterns)), None)


def _check_compliant(value: Any) -> str | None:
    if not (
        isinstance(value, dict)
        and isinstance(value.get("text"), str)
        and isinstance(value.get("tools"), list)
    ):
        return "compliant: needs a 'text' string and a 'tools' list"
    if not all(
        isinstance(t, dict) and isinstance(t.get("name"), str) and isinstance(t.get("input"), dict)
        for t in value["tools"]
    ):
        return "compliant: each tool needs a 'name' string and an 'input' object"
    return None


def _field_problem(raw: dict[str, Any]) -> str | None:
    """The first malformed field of a raw point, as 'field: reason', or None."""
    for key in POINT_STRINGS:
        if not (isinstance(raw.get(key), str) and raw[key].strip()):
            return f"{key}: must be a non-empty string"
    return (
        _other_problem(raw)
        or _check_rule(raw.get("rule"))
        or _check_compliant(raw.get("compliant"))
    )


def _other_problem(raw: dict[str, Any]) -> str | None:
    cut = raw.get("cut_line")
    if isinstance(cut, bool) or not isinstance(cut, int) or cut < 0:
        return "cut_line: must be a non-negative integer"
    markers = raw.get("markers")
    if not (
        isinstance(markers, list) and markers and all(isinstance(m, str) and m for m in markers)
    ):
        return "markers: must be a non-empty list of strings"
    if raw.get("topic") is not None and not isinstance(raw["topic"], str):
        return "topic: must be a string or null"
    if raw.get("commit") is not None and not isinstance(raw["commit"], str):
        return "commit: must be a string when present"
    return None


def load_points(path: Path) -> list[Point]:
    """Read and validate a points file; a malformed point raises ValueError naming the point and the field."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("points file: must be a non-empty JSON list")
    points = []
    for index, raw in enumerate(data):
        label = (
            raw.get("name")
            if isinstance(raw, dict) and isinstance(raw.get("name"), str)
            else f"#{index}"
        )
        problem = "must be an object" if not isinstance(raw, dict) else _field_problem(raw)
        if problem:
            raise ValueError(f"point {label}: {problem}")
        points.append(
            Point(
                raw["name"],
                Path(raw["transcript"]).expanduser(),
                raw["cut_line"],
                raw["markers"],
                raw["lesson_line"],
                raw["topic"],
                raw["question"],
                raw["rule"],
                Message(raw["compliant"]["text"], raw["compliant"]["tools"]),
                raw.get("commit"),
            )
        )
    return points


# --- messages ------------------------------------------------------------------------------------------------


def _blocks(entry_message: dict[str, Any]) -> list[dict[str, Any]]:
    content = entry_message.get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _add_blocks(message: Message, blocks: list[dict[str, Any]]) -> None:
    texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    message.text = "\n".join(filter(None, [message.text, *texts]))
    message.tools += [
        {"name": b.get("name", ""), "input": b.get("input") or {}}
        for b in blocks
        if b.get("type") == "tool_use"
    ]


def _is_main_assistant(entry: dict[str, Any]) -> bool:
    return entry.get("type") == "assistant" and not entry.get("isSidechain")


def _message_id(entry: dict[str, Any]) -> str | None:
    message = entry.get("message")
    return message.get("id") if isinstance(message, dict) else None


def read_entries(path: Path) -> list[dict[str, Any]]:
    """Every line of a transcript as an entry (a blank line becomes `{}`, so indexes stay line numbers)."""
    return [
        json.loads(line) if line.strip() else {}
        for line in path.read_text(encoding="utf-8").split("\n")
    ]


def original_message(entries: list[dict[str, Any]], cut_line: int) -> Message:
    """The failing assistant message: every main-chain assistant entry sharing the `message.id` at `cut_line`."""
    target = _message_id(entries[cut_line]) if _is_main_assistant(entries[cut_line]) else None
    if target is None:
        raise ValueError(f"cut_line {cut_line}: not a main-chain assistant entry with a message id")
    message = Message()
    for entry in entries:
        if _is_main_assistant(entry) and _message_id(entry) == target:
            _add_blocks(message, _blocks(entry["message"]))
    return message


def stream_message(events: list[dict[str, Any]]) -> Message:
    """The assistant events of a stream-json run before the first tool result or the result event."""
    message = Message()
    for event in events:
        kind = event.get("type")
        if kind == "result" or (
            kind == "user"
            and any(b.get("type") == "tool_result" for b in _blocks(event.get("message") or {}))
        ):
            break
        if kind == "assistant":
            _add_blocks(message, _blocks(event.get("message") or {}))
    return message


def score_by_code(rule: dict[str, Any], message: Message) -> bool:
    """True when the message passes a `code` rule."""
    if rule.get("kind") != "code":
        raise ValueError("score_by_code needs a rule of kind 'code'")
    commands = [str(t["input"].get("command", "")) for t in message.tools if t["name"] == "Bash"]
    values = {
        "tool": [t["name"] for t in message.tools],
        "command": commands,
        "text": [message.text],
        "input": [json.dumps(t["input"], sort_keys=True) for t in message.tools],
    }
    hits = [any(re.search(p["regex"], v) for v in values[p["field"]]) for p in rule["patterns"]]
    return any(hits) if rule["pass_when"] == "any" else not any(hits)


# --- the copy ------------------------------------------------------------------------------------------------


def slug(work: Path) -> str:
    """The `~/.claude/projects` folder name of a working folder (the rule of `trial_env.leftover_folders`)."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(work.resolve()))


def first_of_message(entries: list[dict[str, Any]], cut_line: int) -> int:
    """Index of the first entry of the assistant message that holds `cut_line`."""
    target = _message_id(entries[cut_line])
    first = cut_line
    while (
        first > 0
        and _is_main_assistant(entries[first - 1])
        and _message_id(entries[first - 1]) == target
    ):
        first -= 1
    return first


def _context_tokens(entries: list[dict[str, Any]]) -> int:
    for entry in reversed(entries):
        usage = (entry.get("message") or {}).get("usage") if _is_main_assistant(entry) else None
        if isinstance(usage, dict):
            return sum(int(usage.get(key) or 0) for key in USAGE_KEYS)
    return 0


def _distinct(entries: list[dict[str, Any]], key: str) -> list[str]:
    return sorted(
        {e[key] for e in entries if isinstance(e.get(key), str) and e[key]}, key=len, reverse=True
    )


def _rename(line: str, renames: list[tuple[str, str]]) -> str:
    for old, new in renames:
        line = line.replace(old, new)
    return line


def make_copy(point: Point, work: Path) -> Copy:
    """Write lines `[0, first)` of the transcript, rewritten for a new session id and working folder `work`."""
    lines = point.transcript.read_text(encoding="utf-8").split("\n")
    entries = read_entries(point.transcript)
    if point.cut_line >= len(entries):
        raise ValueError(f"cut_line {point.cut_line}: the transcript has {len(entries)} lines")
    first = first_of_message(entries, point.cut_line)
    kept = [
        (line, e)
        for line, e in zip(lines[:first], entries[:first], strict=True)
        if e.get("type") != "cost-state"
    ]
    old_ids = set(_distinct([e for _, e in kept], "sessionId"))
    old_cwds = _distinct([e for _, e in kept], "cwd")
    session_id = str(uuid.uuid4())
    renames = [(old, session_id) for old in old_ids] + [
        (json.dumps(cwd)[1:-1], json.dumps(str(work))[1:-1]) for cwd in old_cwds
    ]
    out = [_rename(line, renames) for line, _ in kept]
    folder = PROJECTS / slug(work)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session_id}.jsonl"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return Copy(
        session_id,
        path,
        work,
        PROMPT,
        _context_tokens([e for _, e in kept]),
        str(entries[first].get("timestamp", "")),
        first,
    )


def cleanup(copy: Copy) -> None:
    """Remove the `~/.claude/projects/<slug>` folder the copy was written to."""
    folder = copy.path.parent
    assert folder.parent == PROJECTS, f"not a projects folder: {folder}"
    shutil.rmtree(folder, ignore_errors=True)


# --- the session's own block ---------------------------------------------------------------------------------


def _text_of(attachment: dict[str, Any]) -> str:
    content = attachment.get("content")
    if isinstance(content, str):
        return content
    stdout = attachment.get("stdout")
    return stdout if isinstance(stdout, str) else ""


def session_start_blocks(entries: list[dict[str, Any]]) -> list[str]:
    """The text of every SessionStart hook attachment."""
    found = []
    for entry in entries:
        att = entry.get("attachment")
        if (
            entry.get("type") == "attachment"
            and isinstance(att, dict)
            and att.get("hookEvent") == "SessionStart"
        ):
            found.append(
                _text_of(att)
                if att.get("type") == "hook_success"
                else json.dumps(att.get("content"))
            )
    return found


def block_r0(copy: Copy) -> str:
    """The lessons block the original session received at its start, read from the copy."""
    for entry in read_entries(copy.path):
        att = entry.get("attachment")
        if (
            entry.get("type") == "attachment"
            and isinstance(att, dict)
            and att.get("type") == "hook_success"
            and att.get("hookEvent") == "SessionStart"
            and BLOCK_PHRASE in _text_of(att)
        ):
            return _text_of(att)
    raise ValueError("no SessionStart hook_success attachment holds the lessons block")


def block_r(block: str, lesson_line: str, topic: str | None) -> str:
    """The block with `- <lesson_line>` after the last bullet under the `<topic>:` heading, else appended."""
    lines = block.split("\n")
    new = f"- {lesson_line}"
    heading = next(
        (i for i, line in enumerate(lines) if topic and line.startswith(f"{topic}:")), None
    )
    if heading is None:
        trailing = "\n" if block.endswith("\n") else ""
        return f"{block.rstrip(chr(10))}\n{topic or 'other'}:\n{new}{trailing}"
    last = heading
    while last + 1 < len(lines) and lines[last + 1].startswith("- "):
        last += 1
    return "\n".join([*lines[: last + 1], new, *lines[last + 1 :]])


# --- per-point checks ----------------------------------------------------------------------------------------


def _marker_problems(point: Point, blocks: list[str]) -> list[str]:
    return [
        f"marker {word!r} occurs in a SessionStart block before the cut"
        for word in point.markers
        if any(re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE) for text in blocks)
    ]


def _rule_problems(point: Point) -> list[str]:
    if point.rule["kind"] == "judge":
        print(f"{point.name}: judge controls: pending part B")
        return []
    original = original_message(read_entries(point.transcript), point.cut_line)
    problems = []
    if score_by_code(point.rule, original):
        problems.append("rule passes the original failing message")
    if not score_by_code(point.rule, point.compliant):
        problems.append("rule fails the compliant message")
    return problems


def _block_problems(point: Point, copy: Copy) -> list[str]:
    try:
        r0 = block_r0(copy)
    except ValueError as err:
        return [str(err)]
    problems = []
    if point.lesson_line in r0:
        problems.append("the lesson line is already in the session's block")
    if point.lesson_line not in block_r(r0, point.lesson_line, point.topic):
        problems.append("block_r lacks the lesson line")
    return problems


def check_copy(point: Point, copy: Copy, max_context: int = DEFAULT_MAX_CONTEXT) -> list[str]:
    """The problems of a point whose copy is built; empty when it is usable."""
    kept = read_entries(copy.path)
    problems = _marker_problems(point, session_start_blocks(kept))
    if any(e.get("subtype") == "compact_boundary" for e in kept):
        problems.append("a compaction lies before the cut")
    if copy.context_tokens > max_context:
        problems.append(f"context {copy.context_tokens} tokens is over {max_context}")
    return [*problems, *_rule_problems(point), *_block_problems(point, copy)]


def check_point(point: Point, work: Path, max_context: int = DEFAULT_MAX_CONTEXT) -> list[str]:
    """Build the copy for working folder `work`, check the point, and remove the copy."""
    copy = make_copy(point, work)
    try:
        return check_copy(point, copy, max_context)
    finally:
        cleanup(copy)


# --- arm files and working folder ----------------------------------------------------------------------------


def arm_settings(work: Path, arm: str, block_text: str) -> Path:
    """Settings for one arm: a `resume` SessionStart hook that prints the block, and a PreToolUse hook that denies."""
    block_file = work / f"block-{arm}.txt"
    block_file.write_text(block_text, encoding="utf-8")
    path = write_settings(work, arm, block_file)  # the pilot's hook: `cat <file>`
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings["hooks"]["SessionStart"][0]["matcher"] = "resume"
    deny = f"cat > /dev/null; printf '%s' '{json.dumps(DENY_OUTPUT)}'"
    settings["hooks"]["PreToolUse"] = [
        {"matcher": "*", "hooks": [{"type": "command", "command": deny}]}
    ]
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path


def make_worktree(point: Point, copy: Copy, base: Path) -> Path:
    """A detached worktree of this repository at `<base>/<name>`, at the point's commit or the last one before the cut."""
    commit = (
        point.commit
        or subprocess.run(
            ["git", "rev-list", "-1", f"--before={copy.cut_timestamp}", "origin/dev"],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    if not commit:
        raise ValueError(f"no commit of origin/dev before {copy.cut_timestamp}")
    path = base / point.name
    base.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(path), commit],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def remove_worktree(path: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(path)],
        cwd=REPO,
        check=False,
        capture_output=True,
    )


# --- self-check ----------------------------------------------------------------------------------------------

OLD_CWD = "/synthetic/original dir"
OLD_SESSION = "00000000-0000-4000-8000-000000000001"
BLOCK = f"Notes: {BLOCK_PHRASE}\nalpha:\n- one\n- two\nbeta:\n- three\n"
LESSON = "Never run the forbidden command"
USAGE = {"input_tokens": 10, "cache_read_input_tokens": 200, "cache_creation_input_tokens": 30}


def _entry(kind: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "isSidechain": False,
        "cwd": OLD_CWD,
        "sessionId": OLD_SESSION,
        "timestamp": "2026-01-02T03:04:05.000Z",
        **fields,
    }


def _assistant(message_id: str, block: dict[str, Any]) -> dict[str, Any]:
    return _entry("assistant", message={"id": message_id, "content": [block], "usage": USAGE})


def synthetic_entries(*, compaction: bool = False) -> list[dict[str, Any]]:
    start = _entry(
        "attachment",
        attachment={
            "type": "hook_success",
            "hookEvent": "SessionStart",
            "content": BLOCK,
            "stdout": BLOCK,
        },
    )
    entries = [
        start,
        _entry("user", message={"role": "user", "content": "do the task"}),
        _assistant("m1", {"type": "thinking", "thinking": "..."}),
        _assistant("m1", {"type": "tool_use", "name": "Read", "input": {"file_path": "a"}}),
        _entry(
            "user", message={"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}
        ),
        _entry("cost-state", costUSD=9.0),
    ]
    if compaction:
        entries.insert(4, _entry("system", subtype="compact_boundary"))
    return [
        *entries,
        _assistant("m2", {"type": "text", "text": "I will clean up."}),
        _assistant(
            "m2", {"type": "tool_use", "name": "Bash", "input": {"command": "rm -rf build"}}
        ),
    ]


def synthetic_point(base: Path, entries: list[dict[str, Any]], **over: Any) -> Point:
    transcript = base / "original.jsonl"
    transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    rule = {
        "kind": "code",
        "pass_when": "none",
        "patterns": [{"field": "command", "regex": r"rm -rf"}],
    }
    point = Point(
        "synthetic",
        transcript,
        len(entries) - 1,
        ["forbidden"],
        LESSON,
        "beta",
        "Did it avoid rm?",
        rule,
        Message("I will only list.", [{"name": "Bash", "input": {"command": "ls"}}]),
    )
    for key, value in over.items():
        setattr(point, key, value)
    return point


def check_copy_shape(base: Path) -> None:
    point = synthetic_point(base, synthetic_entries())
    work = base / "new work"
    copy = make_copy(point, work)
    try:
        assert copy.first == len(synthetic_entries()) - 2, (
            copy.first
        )  # walked back to the message's first entry
        text = copy.path.read_text(encoding="utf-8")
        kept = [json.loads(line) for line in text.splitlines()]
        assert len(kept) == copy.first - 1 and not any(e["type"] == "cost-state" for e in kept), (
            "cost-state kept"
        )
        assert OLD_SESSION not in text and OLD_CWD not in text, "old session id or folder left"
        assert {e["sessionId"] for e in kept} == {copy.session_id} and {e["cwd"] for e in kept} == {
            str(work)
        }
        assert copy.path.parent == PROJECTS / slug(work) and copy.path.stem == copy.session_id
        assert copy.prompt == PROMPT and copy.context_tokens == sum(USAGE.values()), (
            copy.context_tokens
        )
        assert copy.cut_timestamp == "2026-01-02T03:04:05.000Z"
        r0 = block_r0(copy)
        assert r0 == BLOCK
        gained = [
            d
            for d in difflib.ndiff(r0.splitlines(), block_r(r0, LESSON, "beta").splitlines())
            if d[0] in "+-"
        ]
        assert gained == [f"+ - {LESSON}"], gained
        under = block_r(r0, LESSON, "alpha").splitlines()
        assert under.index(f"- {LESSON}") == under.index("- two") + 1, under
        appended = block_r(r0, LESSON, None).splitlines()
        assert appended[-2:] == ["other:", f"- {LESSON}"] and appended[:-2] == r0.splitlines()
    finally:
        cleanup(copy)
    assert not copy.path.parent.exists(), "cleanup left the folder"


def check_scoring() -> None:
    entries = synthetic_entries()
    point = synthetic_point(Path(tempfile.mkdtemp()), entries)
    original = original_message(read_entries(point.transcript), point.cut_line)
    assert original.text == "I will clean up." and [t["name"] for t in original.tools] == [
        "Bash"
    ], original
    assert not score_by_code(point.rule, original) and score_by_code(point.rule, point.compliant)
    shutil.rmtree(point.transcript.parent)
    stream = [
        {"type": "system"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"a": 1}}]},
        },
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "denied"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "late"}]}},
        {"type": "result"},
    ]
    message = stream_message(stream)
    assert message.text == "hi" and message.tools == [{"name": "Edit", "input": {"a": 1}}], message
    any_rule = {
        "kind": "code",
        "pass_when": "any",
        "patterns": [{"field": "tool", "regex": "^Edit$"}, {"field": "text", "regex": "nope"}],
    }
    assert score_by_code(any_rule, message) and not score_by_code(any_rule, Message("x", []))
    input_rule = {
        "kind": "code",
        "pass_when": "any",
        "patterns": [{"field": "input", "regex": '"a": 1'}],
    }
    assert score_by_code(input_rule, message)


def check_points(base: Path) -> None:
    work = base / "check work"
    assert (
        check_point(synthetic_point(base, synthetic_entries(), markers=["unrelated"]), work) == []
    )
    marked = check_point(synthetic_point(base, synthetic_entries()), work)
    assert not marked, marked  # "forbidden" is not in the block
    bad = check_point(synthetic_point(base, synthetic_entries(), markers=["TWO"]), work)
    assert any("'TWO'" in p for p in bad), bad
    compacted = check_point(synthetic_point(base, synthetic_entries(compaction=True)), work)
    assert any("compaction" in p for p in compacted), compacted
    assert any(
        "context" in p for p in check_point(synthetic_point(base, synthetic_entries()), work, 5)
    )
    weak = {"kind": "code", "pass_when": "none", "patterns": [{"field": "command", "regex": "zzz"}]}
    assert any(
        "original" in p
        for p in check_point(synthetic_point(base, synthetic_entries(), rule=weak), work)
    )
    dup = check_point(synthetic_point(base, synthetic_entries(), lesson_line="one"), work)
    assert any("already" in p for p in dup), dup
    assert not list(PROJECTS.glob(f"{slug(work)}*")), "check_point left a copy"


def check_files(base: Path) -> None:
    path = arm_settings(base, "R", "block text\n")
    settings = json.loads(path.read_text(encoding="utf-8"))
    start = settings["hooks"]["SessionStart"][0]
    assert (
        start["matcher"] == "resume"
        and (base / "block-R.txt").read_text(encoding="utf-8") == "block text\n"
    )
    assert start["hooks"][0]["command"] == f"cat {base / 'block-R.txt'}", start
    pre = settings["hooks"]["PreToolUse"][0]
    assert pre["matcher"] == "*"
    run = subprocess.run(
        pre["hooks"][0]["command"],
        shell=True,
        input="{}",
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(run.stdout) == DENY_OUTPUT, run.stdout
    shown = subprocess.run(
        start["hooks"][0]["command"], shell=True, capture_output=True, text=True, check=True
    )
    assert shown.stdout == "block text\n"


def check_loading(base: Path) -> None:
    good = {
        "name": "p",
        "transcript": "t.jsonl",
        "cut_line": 3,
        "markers": ["w"],
        "lesson_line": "l",
        "topic": None,
        "question": "q?",
        "rule": {"kind": "judge"},
        "compliant": {"text": "t", "tools": []},
    }
    path = base / "points.json"
    path.write_text(json.dumps([good]), encoding="utf-8")
    assert load_points(path)[0].commit is None
    broken = [
        ({**good, "cut_line": "3"}, "cut_line"),
        ({**good, "markers": []}, "markers"),
        ({**good, "rule": {"kind": "code", "pass_when": "some", "patterns": []}}, "pass_when"),
        ({**good, "compliant": {"text": "t"}}, "compliant"),
        (
            {
                **good,
                "rule": {
                    "kind": "code",
                    "pass_when": "any",
                    "patterns": [{"field": "tool", "regex": "("}],
                },
            },
            "regex",
        ),
    ]
    for point, name in broken:
        path.write_text(json.dumps([point]), encoding="utf-8")
        try:
            load_points(path)
        except ValueError as err:
            assert "point p" in str(err) and name in str(err), err
        else:
            raise AssertionError(f"accepted a bad {name}")


def self_check() -> int:
    base = Path(tempfile.mkdtemp(prefix="lessons-replay-check-")).resolve()
    assert not base.is_relative_to(REPO)
    try:
        check_copy_shape(base)
        check_scoring()
        check_points(base)
        check_files(base)
        check_loading(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("self-check passed")
    return 0


# --- command line --------------------------------------------------------------------------------------------


def check_command(points_file: Path, max_context: int) -> int:
    points = load_points(points_file)
    bad = 0
    for point in points:
        work = BASE / point.name
        copy = make_copy(point, work)
        tree: Path | None = None
        try:
            tree = make_worktree(point, copy, BASE)
            problems = check_copy(point, copy, max_context)
        except (OSError, ValueError, subprocess.CalledProcessError) as err:
            problems = [f"{type(err).__name__}: {err}"]
        finally:
            cleanup(copy)
            if tree is not None:
                remove_worktree(tree)
        bad += bool(problems)
        print(
            f"{point.name}\t{copy.context_tokens}\t{'ok' if not problems else '; '.join(problems)}"
        )
    return EXIT_PROBLEMS if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("command", nargs="?", choices=["check"])
    parser.add_argument("points", nargs="?", type=Path)
    parser.add_argument("--max-context", type=int, default=DEFAULT_MAX_CONTEXT)
    parser.add_argument("--self-check", action="store_true", help="synthetic transcript; no model")
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    if args.command != "check" or args.points is None:
        parser.error("usage: replay.py check POINTS_FILE | replay.py --self-check")
    return check_command(args.points, args.max_context)


if __name__ == "__main__":
    sys.exit(main())
