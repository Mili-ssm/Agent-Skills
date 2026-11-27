"""Pieces of an extract line that every transcript decoder shares: the length limits and how a text,
a tool call and a tool result become a line. Pure; standard library only."""

HUMAN_LIMIT = 2000  # an owner's words are kept longer than a subagent report
REPORT_LIMIT = 800
AGENT_LIMIT = 1500
ARG_LIMIT = 200
ERROR_LIMIT = 400
_TOOL_ARGS = ("command", "file_path", "description")


def flat(text: str, limit: int) -> str:
    # cut before normalizing so memory does not follow the size of the line; a text that is mostly
    # whitespace can come out shorter than `limit` with its tail lost, which is accepted
    return " ".join(text[: limit * 8].split())[:limit].strip()


def text_of(content: object) -> str:
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


def name_of(value: object) -> str:
    return value if isinstance(value, str) and value else "?"


def tool_arg(inp: object) -> str:
    if not isinstance(inp, dict):
        return ""
    for key in _TOOL_ARGS:
        value = inp.get(key)
        if isinstance(value, str):
            return value
    return ""


def tool_use_line(b: dict, names: dict) -> str:
    name = name_of(b.get("name"))
    if isinstance(b.get("id"), str):
        names[b["id"]] = name
    return f"TOOL {name}: {flat(tool_arg(b.get('input')), ARG_LIMIT)}"


def result_event(b: dict, name: str, state: dict) -> str | None:
    if b.get("is_error"):
        state[name] = True
        return f"TOOL ERROR {name}: {flat(text_of(b.get('content')), ERROR_LIMIT)}"
    was_failing = state.get(name)
    state[name] = False
    if name == "AskUserQuestion":
        return f"OWNER ANSWER: {flat(text_of(b.get('content')), REPORT_LIMIT)}"
    return f"TOOL OK {name}" if was_failing else None
