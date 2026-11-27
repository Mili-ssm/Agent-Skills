"""One test per gap of usage_dispatch_value.py that the stage 0 work closed."""

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
import usage_dispatch_value as dv

SINCE = "2000-01-01T00:00:00"
IMPLEMENTER_CAP = 60  # maxTurns of plugins/agent-skills/agents/implementer.md
FRAME = (
    "Another Claude session sent a message:\n"
    '<agent-message from="abc123">\n'
    "[Subagent hand-back] frame text. The report follows:\n"
)
HANDBACK = FRAME + "  ## Result: DONE\n  see foo.md\n</agent-message>\n\nTrailing frame."
NOTIFICATION = (
    "<task-notification>\n<task-id>abc123</task-id>\n<status>completed</status>\n"
    "<result>## Result: DONE\nsee foo.md</result>\n</task-notification>"
)


def write(path: Path, records: list[dict[str, object]]) -> Path:
    """Write records as a JSONL transcript."""
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def assistant(n: int, blocks: list[dict[str, object]]) -> dict[str, object]:
    """Return a main API call with the given content blocks."""
    return {
        "type": "assistant",
        "timestamp": f"2026-01-01T00:00:{n:02d}Z",
        "message": {
            "id": f"m{n}",
            "model": "claude-sonnet-5",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": blocks,
        },
    }


def dispatch_call(n: int) -> dict[str, object]:
    """Return a main call that dispatches an implementer."""
    block = {
        "type": "tool_use",
        "id": "t1",
        "name": "Agent",
        "input": {"subagent_type": "agent-skills:implementer", "prompt": "do it"},
    }
    return assistant(n, [block])


def launched() -> dict[str, object]:
    """Return the launch acknowledgement of the dispatch."""
    block = {
        "type": "tool_result",
        "tool_use_id": "t1",
        "content": "Async agent launched\nagentId: abc123",
    }
    return {"type": "user", "timestamp": "2026-01-01T00:00:02Z", "message": {"content": [block]}}


def handback_user(text: str = HANDBACK) -> dict[str, object]:
    """Return the hand-back as a user record."""
    return {"type": "user", "timestamp": "2026-01-01T00:00:09Z", "message": {"content": text}}


def notification_attachment() -> dict[str, object]:
    """Return the completion notification as a queued command."""
    return {
        "type": "attachment",
        "timestamp": "2026-01-01T00:00:08Z",
        "attachment": {"type": "queued_command", "prompt": NOTIFICATION},
    }


def test_both_texts_count_and_the_report_is_the_handback_body(tmp_path: Path) -> None:
    """The hand-back and the notification are two texts of one dispatch: both count."""
    path = write(
        tmp_path / "a.jsonl",
        [dispatch_call(1), launched(), notification_attachment(), handback_user()],
    )
    main = dv.parse_main(path, SINCE, set())
    dispatch = main.dispatches["t1"]
    assert len(main.seen_notice) == 2  # ruff: ignore[magic-value-comparison]
    assert dispatch.side_chars >= len(HANDBACK) + len(NOTIFICATION)
    assert dispatch.texts == {"handback", "notification"}
    assert dispatch.report_text == "## Result: DONE\nsee foo.md"


def test_report_comes_from_the_notification_when_it_is_the_only_text(tmp_path: Path) -> None:
    """A notification that arrives first gives the text until the hand-back replaces it."""
    path = write(tmp_path / "a.jsonl", [dispatch_call(1), launched(), notification_attachment()])
    main = dv.parse_main(path, SINCE, set())
    dispatch = main.dispatches["t1"]
    assert len(main.seen_notice) == 1
    assert dispatch.report_text == "## Result: DONE\nsee foo.md"
    assert dispatch.texts == {"notification"}


def test_a_notice_repeated_as_record_and_attachment_counts_once(tmp_path: Path) -> None:
    """The same notice kind delivered twice (user record and attachment) is one text."""
    again = {
        "type": "user",
        "timestamp": "2026-01-01T00:00:10Z",
        "message": {"content": NOTIFICATION},
    }
    path = write(
        tmp_path / "a.jsonl",
        [dispatch_call(1), launched(), notification_attachment(), again],
    )
    main = dv.parse_main(path, SINCE, set())
    assert len(main.seen_notice) == 1
    assert main.dispatches["t1"].texts == {"notification"}


def reopen_main(command: str) -> tuple[dv.Main, dv.Dispatch]:
    """Return a main whose report names foo.md and that then runs the command."""
    main = dv.Main(calls=[dv.Call() for _ in range(3)])
    dispatch = dv.Dispatch("t1", "implementer", "", 0, "")
    dispatch.report_call = 1
    dispatch.report_text = "changed docs/foo.md"
    main.opens.append((2, "t2", command))
    main.result_chars["t2"] = 300
    return main, dispatch


def test_path_match_has_an_end_boundary() -> None:
    """`foo.md` does not match `foo.mdx` or `foo.md-old`, but matches `foo.md:3` and `foo.md.`."""
    for command in ("cat docs/foo.mdx", "cat docs/foo.md-old"):
        main, dispatch = reopen_main(command)
        assert dv.reopened(main, dispatch)[0] == 0
    for command in ("cat docs/foo.md", "grep x docs/foo.md:3", "cat docs/foo.md."):
        main, dispatch = reopen_main(command)
        assert dv.reopened(main, dispatch)[0] == 1


def test_waiting_counts_a_dispatch_that_never_reported() -> None:
    """Text-only calls right after an unreported dispatch count until the main's next tool call."""
    main = dv.Main(calls=[dv.Call(has_tool=True), dv.Call(), dv.Call(), dv.Call(has_tool=True)])
    main.calls.append(dv.Call())
    dispatch = dv.Dispatch("t1", "implementer", "", 0, "")
    assert dv.waiting_calls(main, dispatch) == [1, 2]
    dispatch.report_call = 4
    assert dv.waiting_calls(main, dispatch) == [1, 2]


def test_waiting_stops_at_the_end_of_the_session() -> None:
    """Text-only calls after the last tool call are the final answer, not a wait."""
    main = dv.Main(calls=[dv.Call(has_tool=True), dv.Call(has_tool=True), dv.Call(), dv.Call()])
    dispatch = dv.Dispatch("t1", "implementer", "", 1, "")
    assert dv.waiting_calls(main, dispatch) == []


def test_blocked_and_missing_input_reports() -> None:
    """A report that opens BLOCKED or stops for missing input counts; a DONE report does not."""
    assert dv.opens_blocked("## Result: BLOCKED — turn budget\nrest")
    assert dv.opens_blocked("Status: stopped\nMissing input: no acceptance criteria")
    assert not dv.opens_blocked("## Result: DONE\nnothing was blocked here")


def test_a_report_that_only_mentions_missing_input_is_not_blocked() -> None:
    """`Missing input validation` in a DONE report is a topic, not a stop."""
    done = "## Result: DONE\nMissing input validation was added to the parser.\nrest"
    assert not dv.opens_blocked(done)
    assert not dv.opens_blocked("Missing input validation was added.\nrest")
    assert not dv.opens_blocked("## Result: DONE\nIt needs context from the caller, so I added it.")


def test_empty_sets_print_none_not_zero() -> None:
    """A median, mean or share of nothing is not 0."""
    assert dv.median([]) is None
    assert dv.mean([]) is None
    assert dv.share([]) is None
    assert dv.show(None, ".0f") == "none"
    assert dv.show(2.0, ".1f") == "2.0"


def assistant_record(mid: str, second: int) -> dict[str, object]:
    """Return a subagent API call stamped at the given second of 2026-01-01."""
    return {
        "type": "assistant",
        "timestamp": f"2026-01-01T00:00:{second:02d}Z",
        "message": {
            "id": mid,
            "model": "claude-sonnet-5",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [],
        },
    }


def test_run_turns_include_calls_before_the_window(tmp_path: Path) -> None:
    """A run that started before the window keeps its earlier turns; cost counts the window only."""
    path = write(
        tmp_path / "agent-x.jsonl",
        [assistant_record("a", 1), assistant_record("b", 2), assistant_record("c", 30)],
    )
    run = dv.parse_run(path, "2026-01-01T00:00:10")
    assert run is not None
    assert run.turns == 3  # ruff: ignore[magic-value-comparison]
    one_call = dv.usd({"input_tokens": 1, "output_tokens": 1}, "sonnet")[0]
    assert run.cost == pytest.approx(one_call)
    assert dv.parse_run(path, "2026-01-01T00:01:00") is None


def test_turn_cap_is_read_from_the_agent_frontmatter() -> None:
    """The cap comes from `maxTurns`; a run within two turns of it is near the cap."""
    caps = dv.max_turns()
    assert caps["implementer"] == IMPLEMENTER_CAP
    near, far = (
        dv.Run("implementer", "", "", turns=IMPLEMENTER_CAP - 2),
        dv.Run("implementer", "", "", turns=IMPLEMENTER_CAP - 3),
    )
    assert dv.near_cap(near, caps)
    assert not dv.near_cap(far, caps)
    assert dv.near_cap(dv.Run("no-such-agent", "", "", turns=99), caps) is None


def test_report_size_and_reviewer_rate() -> None:
    """Section G prints median characters and words and the reviewer dispatches per 100 main calls."""
    main = dv.Main(calls=[dv.Call() for _ in range(50)])
    items: list[dv.Item] = []
    for kind in ("skeptical-reviewer", "implementer"):
        dispatch = dv.Dispatch("t", kind, "", 0, "")
        dispatch.report_call, dispatch.report_text = 1, "one two three"
        items.append((main, dispatch))
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        dv.section_g(items, [], ["skeptical-reviewer", "implementer"], 50)
    out = buffer.getvalue()
    assert "reviewer dispatches 1 per 100 main calls (50): 2.00" in out
    assert " 13 " in out
    assert " 3 " in out
