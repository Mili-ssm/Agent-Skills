"""Decode a Codex rollout (`~/.codex/sessions/.../rollout-*.jsonl`) into extract event lines.

Same line format as the Claude decoder in `extract`. The owner's words come only from
`response_item` messages of role `user` (the `event_msg` copies are duplicates); injected
context and developer messages are not the owner's. Shares the line limits and the tool
bookkeeping with the Claude decoder through `event_lines`.
"""

import json
import re

from capture import event_lines as ev

# Only known injected envelopes are filtered: arbitrary snake_case XML can be owner text.
_INJECTED = re.compile(
    r"# AGENTS\.md instructions(?: for /[^\n]+)?[ \t]*\n\s*<INSTRUCTIONS>.*</INSTRUCTIONS>|"
    r"<(environment_context|codex_internal_context|external_codex_apps_[a-z0-9_]+|"
    r"send_user_message_question_reply)(?:\s[^>]*)?>.*</\1>",
    re.DOTALL,
)
_SUBAGENT_ARGS = ("message", "cmd", "target")  # JSON keys of the Codex subagent tools
_SUBAGENT = "\0subagent"  # state key: this rollout is a Codex subagent thread, which yields nothing
_FAILED_PREFIX = "Script failed"
_PROCESS_EXIT = re.compile(r"^Process exited with code (-?\d+)(?:\r?\n|$)")
_OUTPUT_MARK = "Output:\n"
_EXEC_MIN_PARTS = 2  # header and structured result
# Outer types that carry no content for the extract; any other outer type is counted as skipped.
_KNOWN_OUTER = (
    "session_meta",
    "turn_context",
    "event_msg",
    "response_item",
    "compacted",
    "token_usage_record",
    "world_state",
    "inter_agent_communication_metadata",
)
_CALLS = ("custom_tool_call", "function_call")
_OUTPUTS = ("custom_tool_call_output", "function_call_output")


def is_rollout(first_line: str) -> bool:
    """True when the first line of a file is a Codex `session_meta` item."""
    try:
        entry = json.loads(first_line)
    except (ValueError, RecursionError):  # a first line nested deeper than the parser allows
        return False
    return isinstance(entry, dict) and entry.get("type") == "session_meta"


# not `event_lines.text_of`: Codex parts are typed `input_text`/`output_text`, which it skips
def _texts(content: object) -> list[str]:
    if not isinstance(content, list):
        return []
    return [b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]


def _message_events(payload: dict) -> list[str]:
    role = payload.get("role")
    if role == "user":
        texts = [t for t in _texts(payload.get("content")) if not _INJECTED.fullmatch(t.strip())]
        body = ev.flat(" ".join(texts), ev.HUMAN_LIMIT)
        return [f"OWNER: {body}"] if body else []
    if role == "assistant":
        body = ev.flat(" ".join(_texts(payload.get("content"))), ev.AGENT_LIMIT)
        return [f"AGENT: {body}"] if body else []
    return []


def _argument(payload: dict) -> str:
    raw = payload.get("input") if payload.get("type") == "custom_tool_call" else None
    if isinstance(raw, str):
        return raw
    try:
        args = json.loads(payload.get("arguments") or "")
    except (TypeError, ValueError):
        return ""
    return ev.tool_arg(args) or _subagent_arg(args)


def _subagent_arg(args: object) -> str:
    if not isinstance(args, dict):
        return ""
    values = (args.get(key) for key in _SUBAGENT_ARGS)
    return next((v for v in values if isinstance(v, str) and v), "")


def _call_events(payload: dict, names: dict) -> list[str]:
    block = {
        "name": payload.get("name"),
        "id": payload.get("call_id"),
        "input": {"command": _argument(payload)},
    }
    return [ev.tool_use_line(block, names)]


def _output_text(output: object) -> str:
    if isinstance(output, dict):
        return _output_text(output.get("output", output.get("content")))
    return output if isinstance(output, str) else " ".join(_texts(output))


def _exec_result(output: object) -> dict | None:
    """Decode the shell runner's metadata part, separate from the command's own output."""
    parts = _texts(output)
    if len(parts) < _EXEC_MIN_PARTS or not parts[0].startswith("Script completed\nWall time "):
        return None
    try:
        meta = json.loads(parts[1])
    except (ValueError, RecursionError):
        return None
    if (
        isinstance(meta, dict)
        and {"chunk_id", "wall_time_seconds", "exit_code", "output"} <= meta.keys()
    ):
        return meta
    return None


def _output_events(payload: dict, names: dict, state: dict) -> list[str]:
    output = payload.get("output")
    name = names.get(payload.get("call_id"), "?")
    if name == "exec":
        output = _exec_result(output) or output
    text = _output_text(output)
    exit_code = output.get("exit_code") if isinstance(output, dict) else payload.get("exit_code")
    process_exit = _PROCESS_EXIT.match(text)
    failed = (
        (isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0)
        or payload.get("is_error") is True
        or (isinstance(output, dict) and output.get("is_error") is True)
        or text.startswith(_FAILED_PREFIX)
        or (process_exit is not None and process_exit.group(1).lstrip("-").strip("0"))
    )
    if failed:
        text = text.partition(_OUTPUT_MARK)[2] or text
    event = ev.result_event({"is_error": failed, "content": text}, name, state)
    return [event] if event is not None else []


def _item_events(payload: dict, names: dict, state: dict) -> list[str]:
    kind = payload.get("type")
    if kind == "message":
        return _message_events(payload)
    if kind in _CALLS:
        return _call_events(payload, names)
    if kind in _OUTPUTS:
        return _output_events(payload, names, state)
    return []


def events(entry: dict, names: dict, state: dict) -> list[str]:
    """Extract lines (without the line number prefix) of one rollout item."""
    kind = entry.get("type")
    payload = entry.get("payload")
    if kind not in _KNOWN_OUTER:
        raise ValueError(f"unknown rollout item type: {kind!r}")
    if not isinstance(payload, dict):
        return []
    if kind == "session_meta":
        state[_SUBAGENT] = payload.get("thread_source", "user") != "user"
    if kind != "response_item" or state.get(_SUBAGENT):
        return []
    return _item_events(payload, names, state)
