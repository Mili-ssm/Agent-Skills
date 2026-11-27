"""One test per gap of usage_main_calls.py that the stage 0 work closed."""

import json
from pathlib import Path

import usage_main_calls as mc

SINCE = "2000-01-01T00:00:00"


def notice(task_id: str) -> str:
    """Return a task notification text."""
    return f"<task-notification>\n<task-id>{task_id}</task-id>\n</task-notification>"


def call(n: int, command: str | None = None) -> dict[str, object]:
    """Return a main API call; with a command it is one Bash call."""
    content: list[dict[str, object]] = []
    if command is not None:
        content = [
            {"type": "tool_use", "id": f"t{n}", "name": "Bash", "input": {"command": command}}
        ]
    return {
        "type": "assistant",
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {
            "id": f"m{n}",
            "model": "claude-sonnet-5",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": content,
        },
    }


def user_notice(task_id: str) -> dict[str, object]:
    """Return a user record that carries a task notification."""
    return {
        "type": "user",
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {"content": notice(task_id)},
    }


def test_notification_repeated_across_two_calls_counts_once(tmp_path: Path) -> None:
    """The same task id reaching the main before two consecutive calls is one notification."""
    records = [call(1), user_notice("a"), call(2), user_notice("a"), call(3), user_notice("b")]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    calls = mc.parse(path, SINCE)
    assert [c.notifs for c in calls] == [0, 1, 0]
    assert [c.trigger for c in calls][1:] == [mc.NOTIFICATION, mc.OTHER]


def test_lookup_runs_exclude_writes() -> None:
    """Other mem write verbs, redirects to a file and `git -C dir commit` are not lookups."""
    writes = [
        "mem confirm abc",
        "mem supersede a b",
        "cat a > out.txt",
        "echo x >> log",
        "cat a | tee out.txt",
        "git -C /some/dir commit -m x",
        'git -C "a dir" add -A',
    ]
    for command in writes:
        assert mc.Tool("Bash", {"command": command}, "t").is_lookup() is False, command
    reads = [
        "mem search x",
        "cat a 2>&1 | head",
        "grep x f 2>/dev/null",
        "git -C /some/dir log --oneline",
        "ls > /dev/null",
    ]
    for command in reads:
        assert mc.Tool("Bash", {"command": command}, "t").is_lookup() is True, command


def test_single_shell_run_percentiles_and_classes() -> None:
    """Runs of single-Bash calls give length percentiles and the command class of their calls."""

    def bash(command: str) -> mc.Call:
        c = mc.Call(0, (0, 0, 0), 0, 0, mc.OTHER, 0)
        c.tools.append(mc.Tool("Bash", {"command": command}, "t"))
        return c

    text = mc.Call(0, (0, 0, 0), 0, 0, mc.OTHER, 0)
    session = [bash("ls"), bash("ls"), text, bash("cat a"), bash("cat b"), bash("git log"), text]
    assert [len(r) for r in mc.bash_runs(session, 1)] == [2, 3]
    assert [len(r) for r in mc.bash_runs(session)] == [3]
    assert mc.percentile([1, 2, 3, 4, 10], 0.9) == max([1, 2, 3, 4, 10])
    assert mc.percentile([], 0.9) == 0
