"""One test per gap of usage_main_calls.py that the stage 0 work closed."""

import json
from pathlib import Path

import pytest
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


def is_lookup(command: str) -> bool:
    """Tell whether a Bash command counts as a lookup."""
    return mc.Tool("Bash", {"command": command}, "t").is_lookup()


@pytest.mark.parametrize(
    "command",
    [
        "mem confirm abc",
        "mem supersede a b",
        "cat a > out.txt",
        "echo x >> log",
        "cat a &>out.txt",
        "cat a &>> out.txt",
        "cat a >| out.txt",
        "cat a | tee out.txt",
        "git -C /some/dir commit -m x",
        'git -C "a dir" add -A',
    ],
)
def test_write_is_not_a_lookup(command: str) -> None:
    """Each write form (mem verb, redirect, clobber, tee, git -C) is excluded on its own."""
    assert not is_lookup(command)


@pytest.mark.parametrize(
    "command",
    [
        "mem search x",
        "cat a 2>&1 | head",
        "grep x f 2>/dev/null",
        "cat a &>/dev/null",
        "git -C /some/dir log --oneline",
        "ls > /dev/null",
    ],
)
def test_read_stays_a_lookup(command: str) -> None:
    """Discarding or merging output does not make a command a write."""
    assert is_lookup(command)


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
    assert mc.percentile([], 0.9) == 0


@pytest.mark.parametrize(
    ("size", "fraction", "expected"),
    [(10, 0.9, 9), (4, 0.5, 2), (10, 0.95, 10), (100, 0.99, 99), (1, 0.99, 1), (100, 0.29, 29)],
)
def test_percentile_is_the_nearest_rank(size: int, fraction: float, expected: int) -> None:
    """On an exact multiple the rank is not pushed one higher; float error does not move it."""
    assert mc.percentile(list(range(1, size + 1)), fraction) == expected


def test_share_of_nothing_prints_none() -> None:
    """An empty set has no share."""
    assert mc.share(0, 0) == "none"
