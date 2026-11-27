#!/usr/bin/env python3
"""Replay of real failures, part A: everything that needs no model (see README.md, "Replay of real failures").

A real transcript is copied up to the entry just before a known failing assistant message; part B resumes the
copy headless in two arms and scores the next message. This file builds the copy, the arm files, the worktree and
the per-point checks, and scores a message by code.

Usage: replay.py check POINTS_FILE [--max-context N] | replay.py --self-check
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trial_env
from rules_layout.run_trial import write_settings

if TYPE_CHECKING:
    from collections.abc import Callable

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
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
NAME_REFUSED = {".", ".."}
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
    context_tokens: int | None  # None: no assistant entry before the cut has usage
    cut_timestamp: str
    first: int  # index of the first entry of the failing message
    projects: Path = PROJECTS
    created: bool = (
        False  # True only for a projects folder this run made: `cleanup` removes nothing else
    )


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
    if not NAME_RE.fullmatch(raw["name"]) or raw["name"] in NAME_REFUSED:
        return "name: must match [A-Za-z0-9._-]+ and not be '.' or '..'"
    return (
        _shape_problem(raw)
        or _check_rule(raw.get("rule"))
        or _check_compliant(raw.get("compliant"))
    )


def _shape_problem(raw: dict[str, Any]) -> str | None:
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


def _target_id(entries: list[dict[str, Any]], cut_line: int) -> str:
    target = _message_id(entries[cut_line]) if _is_main_assistant(entries[cut_line]) else None
    if target is None:
        raise ValueError(f"cut_line {cut_line}: not a main-chain assistant entry with a message id")
    return target


def original_message(entries: list[dict[str, Any]], cut_line: int) -> Message:
    """The failing assistant message: every main-chain assistant entry sharing the `message.id` at `cut_line`."""
    target = _target_id(entries, cut_line)
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
    """Index of the first entry of the assistant message that holds `cut_line`.

    Attachment or sidechain entries can lie between the message's entries, so this is the earliest main-chain
    assistant entry with the same id, not the end of a run of adjacent ones."""
    target = _target_id(entries, cut_line)
    return next(
        i
        for i, entry in enumerate(entries[: cut_line + 1])
        if _is_main_assistant(entry) and _message_id(entry) == target
    )


def _context_tokens(entries: list[dict[str, Any]]) -> int | None:
    for entry in reversed(entries):
        usage = (entry.get("message") or {}).get("usage") if _is_main_assistant(entry) else None
        if isinstance(usage, dict):
            return sum(int(usage.get(key) or 0) for key in USAGE_KEYS)
    return None


def _distinct(entries: list[dict[str, Any]], key: str) -> list[str]:
    return sorted(
        {e[key] for e in entries if isinstance(e.get(key), str) and e[key]}, key=len, reverse=True
    )


def _json_forms(text: str) -> dict[str, str]:
    """The text as it can sit inside a JSON string: with unicode escapes (the default) and as raw UTF-8."""
    return {json.dumps(text, ensure_ascii=a)[1:-1]: text for a in (True, False)}


def _renamer(
    old_ids: list[str], old_cwds: list[str], session_id: str, work: Path
) -> Callable[[str], str]:
    """A one-pass rewrite of a transcript line: old working folders (at a path boundary) to `work`, old ids to the new one.

    A folder that is a prefix of a longer name (`/a/proj` in `/a/proj-2`, `/a/proj.bak`) or the tail of another path is
    left alone; a JSON escape of a line break or tab before the folder is a boundary, and so is a final `.` ending a sentence."""
    escaped = json.dumps(str(work))[
        1:-1
    ]  # always valid JSON; a raw-UTF-8 old folder gets the raw form
    raw_new = json.dumps(str(work), ensure_ascii=False)[1:-1]
    paths = {
        raw: (escaped if raw.isascii() else raw_new) for cwd in old_cwds for raw in _json_forms(cwd)
    }
    path_re = re.compile(
        rf"(?:(?<![\w.\-])|(?<=\\[ntr]))(?:{'|'.join(map(re.escape, sorted(paths, key=len, reverse=True)))})(?![\w\-]|\.[\w.\-]|\\u)"
        if paths
        else r"(?!)"
    )
    id_re = re.compile(
        rf"(?<![\w\-])(?:{'|'.join(map(re.escape, old_ids))})(?![\w\-])" if old_ids else r"(?!)"
    )

    def rename(line: str) -> str:
        line = path_re.sub(lambda m: paths[m.group(0)], line)
        return id_re.sub(lambda _m: session_id, line)

    return rename


def _make_folder(projects: Path, work: Path) -> Path:
    """Create `<projects>/<slug>`; an existing one is somebody's, so it is refused and left alone."""
    projects.mkdir(parents=True, exist_ok=True)
    folder = projects / slug(work)
    try:
        folder.mkdir()
    except FileExistsError:
        raise FileExistsError(
            f"projects folder {folder.name!r} already exists: not touched; remove it yourself or use another working folder"
        ) from None
    return folder


def make_copy(point: Point, work: Path, projects: Path = PROJECTS) -> Copy:
    """Write lines `[0, first)` of the transcript, rewritten for a new session id and working folder `work`.

    The copy lives in a new `<projects>/<slug>` folder; when that folder exists the call raises and deletes nothing."""
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
    session_id = str(uuid.uuid4())
    rename = _renamer(
        _distinct([e for _, e in kept], "sessionId"),
        _distinct([e for _, e in kept], "cwd"),
        session_id,
        work,
    )
    folder = _make_folder(projects, work)
    path = folder / f"{session_id}.jsonl"
    try:
        path.write_text("\n".join(rename(line) for line, _ in kept) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(
            folder, ignore_errors=True
        )  # the folder is ours: it did not exist a moment ago
        raise
    return Copy(
        session_id,
        path,
        work,
        PROMPT,
        _context_tokens([e for _, e in kept]),
        str(entries[first].get("timestamp", "")),
        first,
        projects,
        created=True,
    )


def cleanup(copy: Copy) -> None:
    """Remove the projects folder `make_copy` created for this copy; refuse any other folder."""
    folder = copy.path.parent
    if not (copy.created and folder.parent == copy.projects and folder.name == slug(copy.work)):
        raise ValueError(f"refusing to remove {folder.name!r}: this run did not create it")
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


# A hook text equal to one the transcript already holds is not sent again (measured with the wire capture
# on 2026-11-27: the unchanged block never reached the request), so both arms end with this line.
REPEAT_NOTE = "(memory: the lessons block, printed again after the session was resumed)"


def block_r0(copy: Copy) -> str:
    """The lessons block the original session received at its start, read from the copy, plus `REPEAT_NOTE`."""
    for entry in read_entries(copy.path):
        att = entry.get("attachment")
        if (
            entry.get("type") == "attachment"
            and isinstance(att, dict)
            and att.get("type") == "hook_success"
            and att.get("hookEvent") == "SessionStart"
            and BLOCK_PHRASE in _text_of(att)
        ):
            return _text_of(att).rstrip("\n") + "\n" + REPEAT_NOTE + "\n"
    raise ValueError("no SessionStart hook_success attachment holds the lessons block")


def block_r(block: str, lesson_line: str, topic: str | None) -> str:
    """The block with `- <lesson_line>` added as one line: after the last bullet under the `<topic>:` heading,
    else (no topic, or no such heading) after the last bullet of the block. No heading is ever added."""
    lines = block.split("\n")
    new = f"- {lesson_line}"
    heading = next(
        (i for i, line in enumerate(lines) if topic and line.startswith(f"{topic}:")), None
    )
    if heading is not None:
        last = heading
        while last + 1 < len(lines) and lines[last + 1].startswith("- "):
            last += 1
    else:
        bullets = [i for i, line in enumerate(lines) if line.startswith("- ")]
        last = bullets[-1] if bullets else max(i for i, line in enumerate(lines) if line.strip())
    return "\n".join([*lines[: last + 1], new, *lines[last + 1 :]])


def one_line_apart(r0: str, r: str, lesson_line: str) -> bool:
    """True when R is R0 plus exactly the lesson's bullet: one line added, none removed."""
    r0_lines, r_lines = r0.split("\n"), r.split("\n")
    return any(
        line == f"- {lesson_line}" and [*r_lines[:i], *r_lines[i + 1 :]] == r0_lines
        for i, line in enumerate(r_lines)
    )


# --- per-point checks ----------------------------------------------------------------------------------------


def _marker_problems(point: Point, blocks: list[str]) -> list[str]:
    return [
        f"marker {word!r} occurs in a SessionStart block before the cut"
        for word in point.markers
        if any(
            re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) for text in blocks
        )
    ]


def _rule_problems(point: Point) -> list[str]:
    if point.rule["kind"] == "judge":
        return []  # its controls need a model: `check_command` reports the point as pending
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
    if not one_line_apart(r0, block_r(r0, point.lesson_line, point.topic), point.lesson_line):
        problems.append("R does not differ from R0 by exactly the lesson line")
    return problems


def check_copy(point: Point, copy: Copy, max_context: int = DEFAULT_MAX_CONTEXT) -> list[str]:
    """The problems of a point whose copy is built; empty when it is usable."""
    kept = read_entries(copy.path)
    problems = _marker_problems(point, session_start_blocks(kept))
    if any(e.get("subtype") == "compact_boundary" for e in kept):
        problems.append("a compaction lies before the cut")
    if copy.context_tokens is None:
        problems.append("context size unknown")
    elif copy.context_tokens > max_context:
        problems.append(f"context {copy.context_tokens} tokens is over {max_context}")
    return [*problems, *_rule_problems(point), *_block_problems(point, copy)]


def check_point(
    point: Point, work: Path, max_context: int = DEFAULT_MAX_CONTEXT, projects: Path = PROJECTS
) -> list[str]:
    """Build the copy for working folder `work`, check the point, and remove the copy."""
    copy = make_copy(point, work, projects)
    try:
        return check_copy(point, copy, max_context)
    finally:
        cleanup(copy)


# --- arm files and working folder ----------------------------------------------------------------------------


def deny_hooks() -> list[dict[str, Any]]:
    """The PreToolUse hooks that deny every tool call."""
    deny = f"cat > /dev/null; printf '%s' '{json.dumps(DENY_OUTPUT)}'"
    return [{"matcher": "*", "hooks": [{"type": "command", "command": deny}]}]


RESUME_MATCHER = "resume|fork"


def arm_settings(work: Path, arm: str, block_text: str) -> Path:
    """Settings for one arm: a SessionStart hook that prints the block on resume, and a PreToolUse hook that denies.

    A `--resume` with `--fork-session` starts with the source `fork`, not `resume` (measured with the wire
    capture on 2026-11-27: a `resume` matcher alone never ran), so the matcher names both."""
    block_file = work / f"block-{arm}.txt"
    block_file.write_text(block_text, encoding="utf-8")
    path = write_settings(work, arm, block_file)  # the pilot's hook: `cat <file>`
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings["hooks"]["SessionStart"][0]["matcher"] = RESUME_MATCHER
    settings["hooks"]["PreToolUse"] = deny_hooks()
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
    if path.exists():
        raise FileExistsError(
            f"worktree folder {point.name!r} already exists under {base.name}: not touched"
        )
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(path), commit],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def remove_worktree(path: Path, base: Path = BASE) -> str | None:
    """Remove a worktree this run made at `<base>/<name>`; refuse any other path. The problem as text, or None."""
    if path.resolve().parent != base.resolve() or not NAME_RE.fullmatch(path.name):
        return f"refused to remove a worktree outside {base.name}"
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(path)],
        cwd=REPO,
        check=False,
        capture_output=True,
    )
    shutil.rmtree(path, ignore_errors=True)
    return f"worktree {path.name!r} could not be removed" if path.exists() else None


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


def synthetic_entries(
    *, compaction: bool = False, interleave: bool = False
) -> list[dict[str, Any]]:
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
    between = (
        [
            _entry("attachment", attachment={"type": "other"}),
            {**_assistant("s1", {"type": "text", "text": "side"}), "isSidechain": True},
        ]
        if interleave
        else []
    )
    return [
        *entries,
        _assistant("m2", {"type": "text", "text": "I will clean up."}),
        *between,
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


def check_copy_shape(base: Path, projects: Path) -> None:
    point = synthetic_point(base, synthetic_entries())
    work = base / "new work"
    copy = make_copy(point, work, projects)
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
        assert copy.path.parent == projects / slug(work) and copy.path.stem == copy.session_id
        assert copy.prompt == PROMPT and copy.context_tokens == sum(USAGE.values()), (
            copy.context_tokens
        )
        assert copy.cut_timestamp == "2026-01-02T03:04:05.000Z"
        r0 = block_r0(copy)
        assert r0 == BLOCK.rstrip("\n") + "\n" + REPEAT_NOTE + "\n"
        gained = [
            d
            for d in difflib.ndiff(r0.splitlines(), block_r(r0, LESSON, "beta").splitlines())
            if d[0] in "+-"
        ]
        assert gained == [f"+ - {LESSON}"], gained
        assert one_line_apart(r0, block_r(r0, LESSON, "beta"), LESSON)
        under = block_r(r0, LESSON, "alpha").splitlines()
        assert under.index(f"- {LESSON}") == under.index("- two") + 1, under
        for topic in (None, "gamma"):  # no heading is added: after the last bullet of the block
            fallback = block_r(r0, LESSON, topic)
            assert one_line_apart(r0, fallback, LESSON), fallback
            assert (
                fallback.splitlines().index(f"- {LESSON}") == r0.splitlines().index("- three") + 1
            )
        assert not one_line_apart(r0, r0 + "other:\n", LESSON)
        assert not one_line_apart(r0, block_r(r0, LESSON, "beta").replace("- one\n", ""), LESSON)
    finally:
        cleanup(copy)
    assert not copy.path.parent.exists(), "cleanup left the folder"
    assert not (PROJECTS / slug(work)).exists(), "the real projects folder was used"


def check_existing_folder(base: Path, projects: Path) -> None:
    """R1: a projects folder that already exists is the owner's; nothing is created in it or deleted from it."""
    point = synthetic_point(base, synthetic_entries())
    work = base / "taken work"
    owned = projects / slug(work)
    owned.mkdir(parents=True)
    (owned / "keep.jsonl").write_text("mine\n", encoding="utf-8")
    try:
        make_copy(point, work, projects)
    except FileExistsError as err:
        assert str(base) not in str(err), err  # the slug only, no path
    else:
        raise AssertionError("make_copy used an existing projects folder")
    assert [p.name for p in owned.iterdir()] == ["keep.jsonl"], "make_copy touched the folder"
    mine = make_copy(point, base / "free work", projects)
    forged = Copy(mine.session_id, owned / "x.jsonl", work, PROMPT, 0, "", 0, projects)
    for bad in (forged, Copy(**{**mine.__dict__, "created": False})):
        try:
            cleanup(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("cleanup removed a folder this run did not create")
    assert (owned / "keep.jsonl").exists() and mine.path.exists()
    cleanup(mine)
    assert not mine.path.parent.exists() and (owned / "keep.jsonl").exists()
    shutil.rmtree(owned)


def check_rewrite(base: Path, projects: Path) -> None:
    """R3: only whole path names change (raw or unicode-escaped); only the exact session id changes."""
    old, uni = "/syn/proj", "/syn/caf\u00e9"
    sid = "00000000-0000-4000-8000-0000000000aa"
    notes = {
        old: f"{old}-2/src {old}/src {old}. /other{old} {old}\n{old}/x\t{old}\r{old} see {old}.bak {old}.",
        uni: f"{uni}/a {uni}s {sid} {sid}0",
    }
    entries = [
        {**_entry("user", message={}), "cwd": cwd, "sessionId": sid, "note": note}
        for cwd, note in notes.items()
    ]
    point = synthetic_point(base, [*entries, _assistant("m3", {"type": "text", "text": "t"})])
    for ascii_json, work in ((False, base / "rw work"), (True, base / "rw w\u00f6rk")):
        # the old folder as raw UTF-8, then as a \u escape; the new one plain, then raw UTF-8
        lines = [json.dumps(e, ensure_ascii=ascii_json) for e in [*entries, _assistant("m3", {})]]
        point.transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
        copy = make_copy(point, work, projects)
        try:
            kept = [json.loads(line) for line in copy.path.read_text(encoding="utf-8").splitlines()]
        finally:
            cleanup(copy)
        assert [e["cwd"] for e in kept] == [str(work)] * 2, kept
        assert kept[0]["note"] == (
            f"{old}-2/src {work}/src {work}. /other{old} {work}\n{work}/x\t{work}\r{work} see {old}.bak {work}."
        ), kept[0]
        assert kept[1]["note"] == f"{work}/a {uni}s {copy.session_id} {sid}0", kept[1]


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


def check_points(base: Path, projects: Path) -> None:
    work = base / "check work"

    def problems(
        entries: list[dict[str, Any]] | None = None, limit: int = DEFAULT_MAX_CONTEXT, **over: Any
    ):
        point = synthetic_point(base, entries or synthetic_entries(), **over)
        return check_point(point, work, limit, projects)

    assert problems(markers=["unrelated"]) == []
    assert problems() == []  # "forbidden" is not in the block
    assert any("'TWO'" in p for p in problems(markers=["TWO"]))
    assert any("compaction" in p for p in problems(synthetic_entries(compaction=True)))
    assert any("context" in p for p in problems(limit=5))
    weak = {"kind": "code", "pass_when": "none", "patterns": [{"field": "command", "regex": "zzz"}]}
    assert any("original" in p for p in problems(rule=weak))
    assert any("already" in p for p in problems(lesson_line="one"))
    for marker in (".env", "C++", "--force"):  # punctuation at an edge: `\\b` would never match
        block = BLOCK.replace("three", f"use {marker} here")
        entries = synthetic_entries()
        entries[0]["attachment"]["content"] = entries[0]["attachment"]["stdout"] = block
        assert any(marker in p for p in problems(entries, markers=[marker])), marker
    assert not any("TW" in p for p in problems(markers=["TW"])), "a marker inside a word matched"
    no_usage = synthetic_entries()
    for entry in no_usage:
        entry.get("message", {}).pop("usage", None)
    assert "context size unknown" in problems(no_usage)
    assert not list(projects.glob(f"{slug(work)}*")), "check_point left a copy"


def check_interleaved(base: Path, projects: Path) -> None:
    """R10: entries between the failing message's own entries do not stop the walk back."""
    entries = synthetic_entries(interleave=True)
    point = synthetic_point(base, entries)
    copy = make_copy(point, base / "gap work", projects)
    try:
        assert copy.first == len(entries) - 4, copy.first
        kept = copy.path.read_text(encoding="utf-8")
        assert "I will clean up." not in kept and "side" not in kept, (
            "the message's first blocks stayed"
        )
    finally:
        cleanup(copy)
    message = original_message(entries, point.cut_line)
    assert message.text == "I will clean up." and [t["name"] for t in message.tools] == ["Bash"]


def check_files(base: Path) -> None:
    path = arm_settings(base, "R", "block text\n")
    settings = json.loads(path.read_text(encoding="utf-8"))
    start = settings["hooks"]["SessionStart"][0]
    assert {"resume", "fork"} <= set(start["matcher"].split("|")), start["matcher"]
    assert (
        start["matcher"] == RESUME_MATCHER
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
    broken += [({**good, "name": bad}, "name") for bad in ("../x", "a/b", "..", ".", "a b")]
    for point, name in broken:
        path.write_text(json.dumps([point]), encoding="utf-8")
        try:
            load_points(path)
        except ValueError as err:
            assert f"point {point['name']}" in str(err) and name in str(err), err
        else:
            raise AssertionError(f"accepted a bad {name}")


def self_check() -> int:
    base = Path(tempfile.mkdtemp(prefix="lessons-replay-check-")).resolve()
    assert not base.is_relative_to(REPO)
    projects = base / "projects"  # never the real ~/.claude/projects
    try:
        check_copy_shape(base, projects)
        check_existing_folder(base, projects)
        check_rewrite(base, projects)
        check_interleaved(base, projects)
        check_scoring()
        check_points(base, projects)
        check_files(base)
        check_loading(base)
        check_command_lines(base, projects)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("self-check passed")
    return 0


# --- command line --------------------------------------------------------------------------------------------


def check_one(
    point: Point, max_context: int, projects: Path = PROJECTS, base: Path = BASE
) -> tuple[int | None, list[str]]:
    """Context tokens and problems of one point; a failure of this point is a problem line, never a traceback."""
    copy: Copy | None = None
    tree: Path | None = None
    problems: list[str] = []
    try:
        copy = make_copy(point, base / point.name, projects)
        tree = make_worktree(point, copy, base)
        problems = check_copy(point, copy, max_context)
    except (OSError, ValueError, subprocess.CalledProcessError) as err:
        problems = [f"{type(err).__name__}: {err}"]
    finally:
        if copy is not None:
            cleanup(copy)
        if tree is not None and (failed := remove_worktree(tree, base)):
            problems.append(failed)
    return (copy.context_tokens if copy else None), problems


def check_command(
    points_file: Path, max_context: int, projects: Path = PROJECTS, base: Path = BASE
) -> int:
    bad = 0
    for point in load_points(points_file):
        tokens, problems = check_one(point, max_context, projects, base)
        status = "ok" if point.rule["kind"] != "judge" else "pending judge controls"
        bad += bool(problems)
        print(
            f"{point.name}\t{tokens if tokens is not None else '?'}\t{'; '.join(problems) or status}"
        )
    return EXIT_PROBLEMS if bad else 0


def _raw_point(point: Point) -> dict[str, Any]:
    return {
        "name": point.name,
        "transcript": str(point.transcript),
        "cut_line": point.cut_line,
        "markers": point.markers,
        "lesson_line": point.lesson_line,
        "topic": point.topic,
        "question": point.question,
        "rule": point.rule,
        "compliant": {"text": point.compliant.text, "tools": point.compliant.tools},
        "commit": "HEAD",
    }


def check_command_lines(base: Path, projects: Path) -> None:
    """R5, R7: one line per point; a bad point does not stop the loop; a judge point is not `ok`."""
    entries = synthetic_entries()
    cases = [
        ("cutbad", {"cut_line": len(entries) + 5}),
        ("missing", {"transcript": base / "absent.jsonl"}),
        ("judged", {"rule": {"kind": "judge"}}),
        ("fine", {}),
    ]
    raw = [_raw_point(synthetic_point(base, entries, name=n, **over)) for n, over in cases]
    points_file = base / "command-points.json"
    points_file.write_text(json.dumps(raw), encoding="utf-8")
    trees = base / "trees"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = check_command(points_file, DEFAULT_MAX_CONTEXT, projects, trees)
    rows = [line.split("\t") for line in out.getvalue().splitlines()]
    assert code == EXIT_PROBLEMS and [r[0] for r in rows] == [c[0] for c in cases], out.getvalue()
    assert "cut_line" in rows[0][2] and "FileNotFoundError" in rows[1][2], rows
    assert rows[2][2] == "pending judge controls" and rows[3][2] == "ok", rows
    assert not list(trees.iterdir()) and not list(projects.iterdir()), "check left a copy"
    assert remove_worktree(base / "elsewhere", trees) is not None  # outside the base: refused


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
