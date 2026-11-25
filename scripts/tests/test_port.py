"""Table tests for the pure text and tool transforms of scripts/port.py."""

from __future__ import annotations

import json
import tomllib

import pytest

import port

AGENTS = {"implementer", "fixer", "check-runner"}


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Use agent-skills:implementer now", "Use implementer now"),
        ("(agent-skills:fixer)", "(fixer)"),
        ("agent-skills:fixer, agent-skills:check-runner.", "fixer, check-runner."),
        # not an agent: skills and commands keep their namespace
        ("agent-skills:prompt-engineering", "agent-skills:prompt-engineering"),
        # a longer word on either side is not a reference
        ("my-agent-skills:implementer", "my-agent-skills:implementer"),
        ("xagent-skills:implementer", "xagent-skills:implementer"),
        ("agent-skills:implementerx", "agent-skills:implementerx"),
        ("agent-skills:implementer_2", "agent-skills:implementer_2"),
        ("no references here", "no references here"),
        # a bare agent name in prose is already unqualified
        ("use fixer", "use fixer"),
    ],
)
def test_rename_agents(text, want):
    assert port.rename_agents(text, AGENTS) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("plain\n", "'''\nplain\n'''"),
        ('has """ inside\n', "'''\nhas \"\"\" inside\n'''"),
        ("back\\slash \\n\n", "'''\nback\\slash \\n\n'''"),
        ("tab\there\nline two\n", "'''\ntab\there\nline two\n'''"),
        # cannot sit in a literal string: escaped basic string instead
        ("no trailing newline", '"no trailing newline"'),
        ("has ''' inside\n", '"has \'\'\' inside\\n"'),
        ("bell\x07\n", '"bell\\u0007\\n"'),
        ("del\x7f\n", '"del\\u007f\\n"'),
    ],
)
def test_toml_multiline(text, want):
    assert port.toml_multiline(text) == want
    assert tomllib.loads("v = " + port.toml_multiline(text))["v"] == text


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("plain", '"plain"'),
        ('say "hi"', '"say \\"hi\\""'),
        ("a\\b", '"a\\\\b"'),
        ("a: [b]", '"a: [b]"'),
        ("line\nbreak", '"line\\nbreak"'),
        ("é", '"é"'),
        ("\x7f", '"\\u007f"'),
    ],
)
def test_q(value, want):
    assert port.q(value) == want
    assert json.loads(port.q(value)) == value


@pytest.mark.parametrize(
    ("tools", "disallowed", "want"),
    [
        (["Read", "Grep"], None, ["read", "search"]),
        (["Edit", "Write"], None, ["edit"]),
        (["Read", "Edit", "Write", "NotebookEdit"], None, ["read", "edit"]),
        (["Read", "Skill"], None, ["read"]),
        (["Grep", "Glob", "Bash"], None, ["search", "execute"]),
        (["WebSearch", "WebFetch"], None, ["web"]),
        (["Read", "mcp__fff__grep"], None, ["read"]),
        (["Read", "Edit", "Write"], ["Edit", "Write"], ["read"]),
        ("Read, Bash", None, ["read", "execute"]),
        ([], None, []),
    ],
)
def test_copilot_tools(tools, disallowed, want):
    fm = {"tools": tools}
    if disallowed is not None:
        fm["disallowedTools"] = disallowed
    assert port.copilot_tools(fm) == want


@pytest.mark.parametrize(
    ("fm", "want"),
    [
        ({"tools": ["Read", "Grep", "Glob"]}, "read files, search file contents, find files by name"),
        ({"tools": ["Read", "Bash"]}, "read files, shell commands"),
        ({"tools": ["Read", "Edit", "Write"]}, "read files, edit files, create files"),
        (
            {"tools": ["Read", "Edit", "Write"], "disallowedTools": ["Edit", "Write"]},
            "read files",
        ),
        ({"tools": ["Read", "mcp__fff__grep", "Skill"]}, "read files, use skills"),
        ({"tools": []}, ""),
    ],
)
def test_codex_capabilities(fm, want):
    assert port.codex_capabilities(fm) == want


READ_ONLY_LINE = "- `Explore` runs on Haiku only with the user-scope override (see the README)."


@pytest.mark.parametrize(
    ("target", "text", "kwargs", "want"),
    [
        # command-only transforms
        (port.COPILOT, f"keep\n{READ_ONLY_LINE}\nafter\n", {"command": True}, "keep\nafter\n"),
        (port.CODEX, f"keep\n{READ_ONLY_LINE}", {"command": True}, "keep\n"),
        # outside a command the line stays; only the built-in name is rewritten
        (
            port.COPILOT,
            f"keep\n{READ_ONLY_LINE}\n",
            {},
            "keep\n- `explore` (built-in agent) runs on Haiku only with the user-scope override (see the README).\n",
        ),
        (port.CODEX, "Do $ARGUMENTS", {"command": True}, f"Do {port.ARGUMENTS_TEXT}"),
        (port.CODEX, "Do $ARGUMENTS", {}, "Do $ARGUMENTS"),
        # slash invocations: bare name on Copilot only
        (port.COPILOT, "run /agent-skills:review now", {}, "run /review now"),
        (port.CODEX, "run /agent-skills:review now", {}, "run /agent-skills:review now"),
        # agent references lose the namespace on both
        (port.COPILOT, "ask agent-skills:fixer", {}, "ask fixer"),
        (port.CODEX, "ask agent-skills:fixer", {}, "ask fixer"),
        # model labels: Codex only
        (port.CODEX, "Haiku (Haiku) reads", {}, "Haiku (gpt-6-luna) reads"),
        (port.CODEX, "(Sonnet) and (Opus)", {}, "(gpt-6.1-terra) and (gpt-6.2-sol)"),
        (port.COPILOT, "(Haiku) and (Sonnet)", {}, "(Haiku) and (Sonnet)"),
        # paths and built-ins
        (port.COPILOT, "${CLAUDE_PLUGIN_ROOT}/x", {}, f"{port.COPILOT_ROOT}/x"),
        (port.CODEX, "${CLAUDE_PLUGIN_ROOT}/x", {}, f"{port.CODEX_ROOT}/x"),
        (port.CODEX, "~/.claude/plugins/p", {}, f"{port.CODEX_BASE}/p"),
        (port.COPILOT, "~/.claude/plugins/p", {}, f"{port.COPILOT_BASE}/p"),
        (port.COPILOT, "${CLAUDE_SKILL_DIR}/a.md", {"skill": "s"}, f"{port.COPILOT_ROOT}/skills/s/a.md"),
        (port.CODEX, "use `Explore`", {}, "use `explorer` (built-in role)"),
        (port.COPILOT, "use `Explore`", {}, "use `explore` (built-in agent)"),
        (port.CODEX, "`AskUserQuestion`", {}, port.ASK_USER_TEXT),
        # delegation rule: agents only
        (port.CODEX, "Delegation rules in CLAUDE.md", {"agent": True}, port.CODEX.delegation),
        (port.COPILOT, "Delegation rules in CLAUDE.md", {"agent": True}, port.COPILOT.delegation),
        (port.CODEX, "Delegation rules in CLAUDE.md", {}, "Delegation rules in CLAUDE.md"),
    ],
)
def test_transform(target, text, kwargs, want):
    assert port.transform(text, target, AGENTS, **kwargs) == want


def test_transform_skill_dir_outside_a_skill_stops():
    with pytest.raises(port.PortError):
        port.transform("${CLAUDE_SKILL_DIR}/a", port.CODEX, AGENTS)


@pytest.mark.parametrize(
    ("target", "text", "want"),
    [
        (port.COPILOT, "clean text", None),
        (port.CODEX, "clean text", None),
        (port.COPILOT, "run /agent-skills:review", "/agent-skills:"),
        (port.CODEX, "run /agent-skills:review", None),  # only Copilot rewrites it
        (port.CODEX, "Haiku (Haiku)", "(Haiku)"),
        (port.CODEX, "(Opus)", "(Opus)"),
        (port.COPILOT, "(Sonnet)", None),  # Copilot keeps model labels
        (port.COPILOT, "${CLAUDE_PLUGIN_ROOT}", "${CLAUDE_"),
        (port.CODEX, "see ~/.claude/plugins", "~/.claude/"),
        (port.CODEX, "use `AskUserQuestion`", "`AskUserQuestion`"),
        (port.COPILOT, "use `Explore`", "`Explore`"),
    ],
)
def test_stale_token(target, text, want):
    assert port.stale_token(text, target) == want


@pytest.mark.parametrize("target", port.TARGETS)
def test_transformed_text_has_no_stale_token(target):
    text = (
        "${CLAUDE_PLUGIN_ROOT}/a ~/.claude/plugins/b `Explore` `AskUserQuestion` "
        "/agent-skills:review (Haiku) (Sonnet) (Opus) agent-skills:fixer"
    )
    assert port.stale_token(port.transform(text, target, AGENTS), target) is None


def test_check_passes_with_block(tmp_path, monkeypatch, capsys):
    """Shared-block markers in a skill reference and an agent must not reach the ports, and --check must still pass."""
    import shutil

    for name in ("plugins/agent-skills", "ports", "user-config", ".claude-plugin", ".github", ".agents"):
        shutil.copytree(port.ROOT / name, tmp_path / name)
    shutil.copy(port.ROOT / "README.md", tmp_path / "README.md")
    monkeypatch.setattr(port, "ROOT", tmp_path)
    monkeypatch.setattr(port, "PLUGIN", tmp_path / "plugins" / "agent-skills")
    monkeypatch.setattr(port, "CLAUDE_MARKETPLACE", tmp_path / ".claude-plugin" / "marketplace.json")
    monkeypatch.setattr(port, "POLICY", tmp_path / "user-config" / "offload-policy.md")
    monkeypatch.setattr(port, "ROUTING", tmp_path / "user-config" / "routing.md")
    monkeypatch.setattr(port, "README", tmp_path / "README.md")

    reference = port.PLUGIN / "skills" / "prompt-engineering" / "references" / "skills-and-agents.md"
    agent = port.PLUGIN / "agents" / "fixer.md"
    for path, line in (
        (reference, "6. **Report**: format and max length."),
        (agent, "## Rules"),
    ):
        text = path.read_text(encoding="utf-8")
        assert text.count(line) == 1
        path.write_text(
            text.replace(line, f"<!-- shared:x -->\n{line}\n<!-- /shared:x -->"),
            encoding="utf-8",
        )

    assert port.main(["--check"]) == 0, capsys.readouterr().out
