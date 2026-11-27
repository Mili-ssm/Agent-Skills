import json

import pytest
from commands import hooks
from test_session_index import TODAY, hook_run, proj, write

__all__ = ["proj"]  # re-exported: pytest finds the fixture in this module by its name


def test_codex_host_drops_the_claude_only_names(proj, monkeypatch):
    write(proj, "s", "S.", kind="state")
    claude = hooks.session_index(None, proj, None, TODAY, limit=8)
    monkeypatch.setenv("MEM_HOST", "codex")
    codex = hooks.session_index(None, proj, None, TODAY, limit=8)
    assert "auto memory" in claude and hooks._STATUS_LINE in claude
    assert "auto memory" not in codex and "memory:memory-" not in codex
    assert "mem memories --kind state" in codex and "mem remember" in codex


def test_codex_due_line_names_the_skill(monkeypatch):
    due = {"merge": 2}
    assert "memory:memory-curator" in hooks._index_due_line(due, True)[0]
    monkeypatch.setenv("MEM_HOST", "codex")
    line = hooks._index_due_line(due, True)[0]
    assert "memory:memory-" not in line and "memory-curation skill" in line


@pytest.mark.parametrize(("host", "logged"), [(None, "claude"), ("codex", "codex")])
def test_hook_log_carries_the_host(tmp_path, monkeypatch, host, logged):
    if host:
        monkeypatch.setenv("MEM_HOST", host)
    else:
        monkeypatch.delenv("MEM_HOST", raising=False)
    monkeypatch.setenv("MEM_PROJECT", str(tmp_path))
    assert hook_run(monkeypatch, tmp_path, json.dumps({"cwd": str(tmp_path)})) == 0
    line = (tmp_path / "data" / "hooks" / "log.jsonl").read_text().splitlines()[-1]
    assert json.loads(line)["host"] == logged


@pytest.mark.parametrize(
    ("claude_text", "codex_text"),
    [
        ("preferences and personal matters -> auto memory; what", "what"),
        (
            "; the project's current situation -> both.",
            "; the project's current situation -> mem remember too.",
        ),
    ],
)
def test_codex_rules_replacements_still_match(claude_text, codex_text):
    # str.replace is silent on no match: a rewording of _INDEX_RULES must fail here, not leak into Codex.
    assert claude_text in hooks._INDEX_RULES
    assert claude_text not in hooks._INDEX_RULES_CODEX
    assert codex_text in hooks._INDEX_RULES_CODEX
