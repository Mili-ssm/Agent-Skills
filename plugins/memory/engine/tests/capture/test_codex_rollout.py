"""`capture.codex_rollout`: Codex rollout files reduced to the same extract lines as Claude transcripts."""

import json
from pathlib import Path

from capture import event_lines
from capture import extract as capture_extract
from entry import capture as capture_entry

FIXTURE = Path(__file__).parent / "fixtures" / "codex-rollout.jsonl"
STAMP = "2026-01-01T00:00:00.000Z"


def item(kind, payload):
    return {"timestamp": STAMP, "type": kind, "payload": payload}


def message(role, *texts):
    kind = "output_text" if role == "assistant" else "input_text"
    return item(
        "response_item",
        {"type": "message", "role": role, "content": [{"type": kind, "text": t} for t in texts]},
    )


def meta(source="user", cwd="/work/demo"):
    return item("session_meta", {"id": "s", "cwd": cwd, "thread_source": source})


def write(tmp_path, entries):
    p = tmp_path / "rollout.jsonl"
    p.write_text("\n".join(e if isinstance(e, str) else json.dumps(e) for e in entries) + "\n")
    return p


def lines(tmp_path, entries):
    return capture_extract.extract(write(tmp_path, entries))[0].splitlines()


def test_owner_prompt_becomes_a_user_event(tmp_path):
    assert lines(tmp_path, [meta(), message("user", "fix the  bug")]) == ["[2] OWNER: fix the bug"]


def test_injected_user_items_are_dropped(tmp_path):
    entries = [
        meta(),
        message("user", "# AGENTS.md instructions for /x\n<INSTRUCTIONS>fixture</INSTRUCTIONS>"),
        message("user", "<environment_context>\n<cwd>/x</cwd>\n</environment_context>"),
        message("developer", "skill body"),
        message("user", "<environment_context>\n</environment_context>", "real words"),
    ]
    assert lines(tmp_path, entries) == ["[5] OWNER: real words"]


def test_user_prompt_counted_once(tmp_path):
    out = capture_extract.extract(FIXTURE)[0]
    assert out.count("please list the demo files") == 1


def test_assistant_message_and_tool_call_events(tmp_path):
    out = lines(
        tmp_path,
        [
            meta(),
            message("assistant", "Looking."),
            item(
                "response_item",
                {"type": "custom_tool_call", "call_id": "c", "name": "exec", "input": "ls -a"},
            ),
            item(
                "response_item",
                {
                    "type": "function_call",
                    "call_id": "d",
                    "name": "shell",
                    "arguments": json.dumps({"command": "pwd"}),
                },
            ),
        ],
    )
    assert out == ["[2] AGENT: Looking.", "[3] TOOL exec: ls -a", "[4] TOOL shell: pwd"]


def test_failed_tool_output_marked_like_claude(tmp_path):
    out = capture_extract.extract(FIXTURE)[0].splitlines()
    assert out == [
        "[8] OWNER: please list the demo files",
        "[14] AGENT: Listing the files now.",
        "[15] TOOL exec: await tools.exec_command({cmd: 'ls'})",
        "[16] TOOL ERROR exec: ls: cannot access demo: No such file",
        "[17] TOOL shell: ls -a",
        "[19] AGENT: Two files: a and b.",
    ]


def test_a_later_success_after_a_failure_is_marked_ok(tmp_path):
    def output(call, text):
        body = [{"type": "input_text", "text": text}]
        return item(
            "response_item", {"type": "custom_tool_call_output", "call_id": call, "output": body}
        )

    def call(call_id):
        return item(
            "response_item",
            {"type": "custom_tool_call", "call_id": call_id, "name": "exec", "input": "x"},
        )

    out = lines(
        tmp_path,
        [
            meta(),
            call("a"),
            output("a", "Script failed\nWall time 1 seconds\nOutput:\nboom"),
            call("b"),
            output("b", "Script completed\nWall time 1 seconds\nOutput:\nfine"),
        ],
    )
    assert out[-1] == "[5] TOOL OK exec" and out[-3] == "[3] TOOL ERROR exec: boom"


def test_meta_only_rollout_gives_empty_extract(tmp_path):
    assert capture_extract.extract(write(tmp_path, [meta()])) == ("", 1)


def test_subagent_rollout_gives_empty_extract(tmp_path):
    entries = [meta("subagent"), message("user", "do this"), message("assistant", "done")]
    assert capture_extract.extract(write(tmp_path, entries)) == ("", 3)


def test_subagent_rollout_stays_empty_when_read_in_windows(tmp_path):
    p = write(tmp_path, [meta("subagent"), message("user", "do this")])
    assert capture_extract.extract(p, since_line=1, forward=True) == ("", 2)


def test_known_ignored_types_not_counted_as_skipped(tmp_path):
    entries = [
        meta(),
        item("event_msg", {"type": "token_count"}),
        item("event_msg", {"type": "user_message", "message": "dup"}),
        {"type": "token_usage_record", "payload": {}},
        {"type": "world_state", "payload": {}},
        {"type": "turn_context", "payload": {"cwd": "/x"}},
        item("compacted", {"message": "", "replacement_history": []}),
        item("response_item", {"type": "reasoning", "summary": []}),
    ]
    assert lines(tmp_path, entries) == [] and capture_extract.last_skipped == 0


def test_unknown_item_counts_as_skipped_not_error(tmp_path):
    out = lines(tmp_path, [meta(), {"type": "brand_new", "payload": {}}, message("user", "ok")])
    assert out == ["[3] OWNER: ok"] and capture_extract.last_skipped == 1


def test_claude_transcript_unchanged(tmp_path):
    entries = [
        {"type": "user", "message": {"content": "hello"}, "origin": {"kind": "human"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
    ]
    p = write(tmp_path, entries)
    assert capture_extract.extract(p) == ("[1] OWNER: hello\n[2] AGENT: hi", 2)
    assert capture_extract.last_skipped == 0


def test_first_cwd_from_session_meta(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    assert capture_entry.first_cwd(write(tmp_path, [meta(cwd=str(project))])) == project


def test_first_cwd_falls_back_to_turn_context(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    entries = [meta(cwd="/no/such/dir"), item("turn_context", {"cwd": str(project)})]
    assert capture_entry.first_cwd(write(tmp_path, entries)) == project


def test_every_observed_injected_wrapper_is_dropped(tmp_path):
    wrappers = [
        "# AGENTS.md instructions for /x\n<INSTRUCTIONS>fixture</INSTRUCTIONS>",
        "<environment_context>\n</environment_context>",
        "<external_codex_apps_open_page>x</external_codex_apps_open_page>",
        "<send_user_message_question_reply>x</send_user_message_question_reply>",
        '  <codex_internal_context kind="a">x</codex_internal_context>',
    ]
    entries = [meta(), *[message("user", w) for w in wrappers]]
    assert lines(tmp_path, entries) == []


def test_owner_html_and_angle_text_are_kept(tmp_path):
    entries = [
        meta(),
        message("user", "<div>hello</div>"),
        message("user", "<3 you, a_b <c>"),
        message("user", "<user_id> is null here"),
        message("user", "<a_b>x</a_b> then my question"),
    ]
    assert lines(tmp_path, entries) == [
        "[2] OWNER: <div>hello</div>",
        "[3] OWNER: <3 you, a_b <c>",
        "[4] OWNER: <user_id> is null here",
        "[5] OWNER: <a_b>x</a_b> then my question",
    ]


def test_injected_first_part_keeps_only_the_prompt(tmp_path):
    entries = [
        meta(),
        message("user", "<codex_internal_context>x</codex_internal_context>", "do it"),
    ]
    assert lines(tmp_path, entries) == ["[2] OWNER: do it"]


def test_image_only_user_message_gives_no_event(tmp_path):
    image = item(
        "response_item",
        {"type": "message", "role": "user", "content": [{"type": "input_image", "image_url": "x"}]},
    )
    assert lines(tmp_path, [meta(), image]) == []


def test_inter_agent_metadata_not_counted_as_skipped(tmp_path):
    entries = [meta(), item("inter_agent_communication_metadata", {"a": 1})]
    assert lines(tmp_path, entries) == [] and capture_extract.last_skipped == 0


def test_subagent_tool_call_prints_its_message(tmp_path):
    call = item(
        "response_item",
        {
            "type": "function_call",
            "name": "spawn_agent",
            "call_id": "c1",
            "arguments": json.dumps({
                "message": "review\n  the   diff " + "x" * 300,
                "target": "t",
            }),
        },
    )
    [line] = lines(tmp_path, [meta(), call])
    assert line.startswith("[2] TOOL spawn_agent: review the diff xxx")
    assert len(line.split(": ", 1)[1]) == event_lines.ARG_LIMIT


def test_owner_xml_and_agents_header_are_not_injected(tmp_path):
    entries = [
        meta(),
        message("user", "<order_id>42</order_id>"),
        message("user", "# AGENTS.md instructions are unclear. Please explain."),
        message("user", "# AGENTS.md instructions for /x\n<INSTRUCTIONS>fixture</INSTRUCTIONS>"),
        message("user", "<environment_context>fixture</environment_context>"),
        message("user", "# AGENTS.md instructions\n\n<INSTRUCTIONS>fixture</INSTRUCTIONS>"),
        message("user", "# AGENTS.md instructions for the bug I need fixed"),
        message("user", "# AGENTS.md instructions for /x\nPlease explain these."),
    ]
    assert lines(tmp_path, entries) == [
        "[2] OWNER: <order_id>42</order_id>",
        "[3] OWNER: # AGENTS.md instructions are unclear. Please explain.",
        "[7] OWNER: # AGENTS.md instructions for the bug I need fixed",
        "[8] OWNER: # AGENTS.md instructions for /x Please explain these.",
    ]


def test_shell_wrapper_exit_code_and_recovery(tmp_path):
    entries = [
        meta(),
        item(
            "response_item",
            {"type": "function_call", "name": "shell", "call_id": "1", "arguments": "{}"},
        ),
        item(
            "response_item",
            {
                "type": "function_call_output",
                "call_id": "1",
                "output": "Process exited with code 1\nOutput:\nfailed",
            },
        ),
        item(
            "response_item",
            {"type": "function_call", "name": "shell", "call_id": "2", "arguments": "{}"},
        ),
        item(
            "response_item",
            {
                "type": "function_call_output",
                "call_id": "2",
                "output": "Process exited with code 0\nOutput:\nok",
            },
        ),
        item(
            "response_item",
            {
                "type": "function_call_output",
                "call_id": "3",
                "output": "The process exited with code 1 in the example",
            },
        ),
    ]
    assert lines(tmp_path, entries) == [
        "[2] TOOL shell: ",
        "[3] TOOL ERROR shell: failed",
        "[4] TOOL shell: ",
        "[5] TOOL OK shell",
    ]


def test_structured_tool_exit_status_and_recovery(tmp_path):
    entries = [
        meta(),
        item(
            "response_item",
            {"type": "function_call", "name": "shell", "call_id": "1", "arguments": "{}"},
        ),
        item(
            "response_item",
            {
                "type": "function_call_output",
                "call_id": "1",
                "output": {"exit_code": 2, "output": "bad"},
            },
        ),
        item(
            "response_item",
            {"type": "function_call", "name": "shell", "call_id": "2", "arguments": "{}"},
        ),
        item(
            "response_item",
            {
                "type": "function_call_output",
                "call_id": "2",
                "output": {"exit_code": 0, "output": "ok"},
            },
        ),
    ]
    assert lines(tmp_path, entries) == [
        "[2] TOOL shell: ",
        "[3] TOOL ERROR shell: bad",
        "[4] TOOL shell: ",
        "[5] TOOL OK shell",
    ]


def test_observed_exec_envelope_records_failure_and_recovery(tmp_path):
    entries = [meta()]
    for code in (1, 0):
        entries.extend([
            item(
                "response_item",
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": str(code),
                    "input": "{}",
                },
            ),
            item(
                "response_item",
                {
                    "type": "custom_tool_call_output",
                    "call_id": str(code),
                    "output": [
                        {
                            "type": "input_text",
                            "text": "Script completed\nWall time 0.1 seconds\nOutput:\n",
                        },
                        {
                            "type": "input_text",
                            "text": json.dumps({
                                "chunk_id": "fixture",
                                "wall_time_seconds": 0.001,
                                "exit_code": code,
                                "original_token_count": 1,
                                "output": "fixture output",
                            }),
                        },
                    ],
                },
            ),
        ])
    assert lines(tmp_path, entries) == [
        "[2] TOOL exec: {}",
        "[3] TOOL ERROR exec: fixture output",
        "[4] TOOL exec: {}",
        "[5] TOOL OK exec",
    ]
