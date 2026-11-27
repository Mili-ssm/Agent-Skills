"""Table tests for the pure text and tool transforms of scripts/port.py."""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from types import SimpleNamespace
from typing import cast

import port
import pytest

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
        ("has ''' inside\n", "\"has ''' inside\\n\""),
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
        (
            {"tools": ["Read", "Grep", "Glob"]},
            "read files, search file contents, find files by name",
        ),
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
        (
            port.COPILOT,
            "${CLAUDE_SKILL_DIR}/a.md",
            {"skill": "s"},
            f"{port.COPILOT_ROOT}/skills/s/a.md",
        ),
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
    for name in (
        "plugins/agent-skills",
        "plugins/memory",
        "ports",
        "user-config",
        ".claude-plugin",
        ".github",
        ".agents",
    ):
        shutil.copytree(port.ROOT / name, tmp_path / name)
    shutil.copy(port.ROOT / "README.md", tmp_path / "README.md")
    (tmp_path / "docs").mkdir()
    shutil.copy(port.ROOT / "docs" / "ports.md", tmp_path / "docs" / "ports.md")
    monkeypatch.setattr(port, "ROOT", tmp_path)
    monkeypatch.setattr(port, "PLUGIN", tmp_path / "plugins" / "agent-skills")
    monkeypatch.setattr(
        port, "CLAUDE_MARKETPLACE", tmp_path / ".claude-plugin" / "marketplace.json"
    )
    monkeypatch.setattr(port, "POLICY", tmp_path / "user-config" / "offload-policy.md")
    monkeypatch.setattr(port, "ROUTING", tmp_path / "user-config" / "routing.md")
    monkeypatch.setattr(port, "README", tmp_path / "README.md")
    monkeypatch.setattr(port, "PORTS_DOC", tmp_path / "docs" / "ports.md")

    reference = (
        port.PLUGIN / "skills" / "prompt-engineering" / "references" / "skills-and-agents.md"
    )
    agent = port.PLUGIN / "agents" / "fixer.md"
    for path, line in (
        (reference, "## Skills"),
        (agent, "## Rules"),
    ):
        text = path.read_text(encoding="utf-8")
        assert text.count(line) == 1
        path.write_text(
            text.replace(line, f"<!-- shared:x -->\n{line}\n<!-- /shared:x -->"),
            encoding="utf-8",
        )

    assert port.main(["--check"]) == 0, capsys.readouterr().out


def test_models_block_is_regenerated_and_requires_markers():
    doc = f"intro\n{port.MODELS_BEGIN}\nstale\n{port.MODELS_END}\noutro\n"
    out = port.models_block(doc, port.CATALOG_DATA)
    assert out is not None
    assert out.startswith(f"intro\n{port.MODELS_BEGIN}\n\n") and out.endswith(
        f"{port.MODELS_END}\noutro\n"
    )
    assert "stale" not in out
    assert "| `fable` | `gpt-6.2-astra` low |" in out
    assert port.models_block("no markers", port.CATALOG_DATA) is None


def test_ports_doc_block_is_current():
    doc = port.PORTS_DOC.read_text(encoding="utf-8")
    assert port.models_block(doc, port.CATALOG_DATA) == doc, "run python3 scripts/port.py"


def test_unused_max_cells_follow_the_effort_policy():
    assert port.CODEX_PAIRS["haiku", "max"] == ("gpt-6.1-terra", "low")
    assert port.CODEX_PAIRS["sonnet", "max"] == ("gpt-6.2-sol", "low")
    assert port.CODEX_PAIRS["opus", "max"] == ("gpt-6.2-astra", "low")
    assert port.CODEX_PAIRS["fable", "max"] == ("gpt-6.2-astra", "xhigh")
    assert port.COPILOT_MODELS["fable"] == "claude-fable-5.2"


def codex_catalog(plugins: list[tuple[str, str]]) -> str:
    entries = [{"name": n, "source": {"source": "local", "path": f"./{f}"}} for n, f in plugins]
    return json.dumps({"name": port.MARKETPLACE, "plugins": entries})


def test_catalog_plugins_add_memory_to_codex_only():
    assert port.catalog_plugins(port.CODEX) == [
        ("agent-skills", port.CODEX.dir),
        ("memory", "plugins/memory"),
    ]
    assert port.catalog_plugins(port.COPILOT) == [("agent-skills", port.COPILOT.dir)]


def test_generated_catalogs_list_memory_for_codex_only():
    codex = json.loads((port.ROOT / port.CODEX.catalog).read_text(encoding="utf-8"))
    copilot = json.loads((port.ROOT / port.COPILOT.catalog).read_text(encoding="utf-8"))
    assert [p["name"] for p in codex["plugins"]] == ["agent-skills", "memory"]
    assert codex["plugins"][1]["source"] == {"source": "local", "path": "./plugins/memory"}
    assert [p["name"] for p in copilot["plugins"]] == ["agent-skills"]


@pytest.mark.parametrize(
    ("plugins", "fragment"),
    [
        ([("agent-skills", "ports/codex/agent-skills")], "listed plugins"),
        ([("agent-skills", "ports/codex/agent-skills"), ("memory", "plugins")], "source"),
        (
            [("agent-skills", "ports/codex/agent-skills"), ("memory", "plugins/nope")],
            "is not a folder",
        ),
    ],
)
def test_checker_rejects_a_missing_or_mispathed_memory_entry(
    tmp_path, monkeypatch, plugins, fragment
):
    (tmp_path / "plugins" / "memory").mkdir(parents=True)
    (tmp_path / "ports" / "codex" / "agent-skills").mkdir(parents=True)
    (tmp_path / ".agents" / "plugins").mkdir(parents=True)
    (tmp_path / port.CODEX.catalog).write_text(codex_catalog(plugins), encoding="utf-8")
    monkeypatch.setattr(port, "ROOT", tmp_path)
    verifier = port.Verifier.__new__(port.Verifier)
    verifier.errors = []
    verifier.src = cast("port.Sources", SimpleNamespace(marketplace={"name": port.MARKETPLACE}))
    verifier.catalog(port.CODEX)
    assert any(fragment in e for e in verifier.errors), verifier.errors


# --- Codex wording rewrites ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def sources():
    src, errors = port.load_sources()
    assert errors == []
    return src


def _source_text(src, key):
    """The Claude source text a CODEX_REWRITES key names."""
    name, _, part = key.partition(":")
    if name == "user-config/offload-policy.md":
        return src.policy
    if name == "user-config/routing.md":
        return src.routing
    folder, _, stem = name.partition("/")
    doc = {"agents": src.agents, "commands": src.commands}[folder][stem.removesuffix(".md")]
    return doc.fm["description"] if part else doc.body


@pytest.mark.parametrize("key", sorted(port.CODEX_REWRITES))
def test_codex_rewrites_apply_to_the_real_sources(sources, key):
    text = _source_text(sources, key)
    out = port.codex_rewrite(text, key)
    for old, new in port.CODEX_REWRITES[key]:
        assert old in text
        assert old not in out
        assert new in out


@pytest.mark.parametrize("key", sorted(port.CODEX_REWRITES))
def test_codex_rewrites_fail_when_the_source_text_is_gone(key):
    with pytest.raises(port.PortError, match="source text not found"):
        port.codex_rewrite("a source that no longer says it", key)


def test_codex_rewrites_leave_copilot_and_unkeyed_text_alone(sources):
    key = "user-config/routing.md"
    text = _source_text(sources, key)
    assert "slash commands in Claude Code" in port.transform(
        text, port.COPILOT, AGENTS, rewrites=key
    )
    assert port.transform("plain", port.CODEX, AGENTS) == "plain"


# --- memory agents as Codex roles (ADR 0038) ----------------------------------------------------

MEMORY_ROLES = port.ROOT / "plugins" / "memory" / "codex-agents"
MEMORY_AGENT_COUNT = 5
MEMORY_AGENT_FILES = sorted((port.ROOT / "plugins" / "memory" / "agents").glob("*.md"))


def test_memory_agents_exist():
    assert len(MEMORY_AGENT_FILES) == MEMORY_AGENT_COUNT
    assert sorted(p.stem for p in MEMORY_ROLES.glob("*.toml")) == [
        p.stem for p in MEMORY_AGENT_FILES
    ]


@pytest.mark.parametrize("source", MEMORY_AGENT_FILES, ids=lambda p: p.stem)
def test_memory_agent_becomes_a_codex_role(sources, source):
    doc = sources.source_agents["memory"][source.stem]
    text = (MEMORY_ROLES / f"{doc.name}.toml").read_text(encoding="utf-8")
    role = tomllib.loads(text)
    model, effort = port.CODEX_PAIRS[doc.fm["model"], doc.fm["effort"]]
    assert role["name"] == doc.name
    assert role["description"]
    assert role["model"] == model
    assert role["model_reasoning_effort"] == effort
    assert role["developer_instructions"].startswith(
        port.transform(doc.body, port.CODEX, set(), agent=True, rewrites=f"agents/{doc.name}.md")
    )
    assert "~/.claude" not in text
    assert port.stale_token(text, port.CODEX) is None
    read_only = bool(port.WRITE_TOOLS & set(port.as_list(doc.fm.get("disallowedTools"))))
    assert (port.READ_ONLY_RULE in role["developer_instructions"]) == read_only


def test_synthesizer_skill_lookup_searches_the_codex_cache():
    role = tomllib.loads((MEMORY_ROLES / "memory-synthesizer.toml").read_text(encoding="utf-8"))
    assert f"find {port.CODEX.base} -path" in role["developer_instructions"]


def _fake_repo(tmp_path, monkeypatch):
    for name in (
        "plugins/agent-skills",
        "plugins/memory",
        "ports",
        "user-config",
        ".claude-plugin",
        ".github",
        ".agents",
    ):
        shutil.copytree(port.ROOT / name, tmp_path / name)
    shutil.copy(port.ROOT / "README.md", tmp_path / "README.md")
    (tmp_path / "docs").mkdir()
    shutil.copy(port.ROOT / "docs" / "ports.md", tmp_path / "docs" / "ports.md")
    monkeypatch.setattr(port, "ROOT", tmp_path)
    monkeypatch.setattr(port, "PLUGIN", tmp_path / "plugins" / "agent-skills")
    monkeypatch.setattr(
        port, "CLAUDE_MARKETPLACE", tmp_path / ".claude-plugin" / "marketplace.json"
    )
    monkeypatch.setattr(port, "POLICY", tmp_path / "user-config" / "offload-policy.md")
    monkeypatch.setattr(port, "ROUTING", tmp_path / "user-config" / "routing.md")
    monkeypatch.setattr(port, "README", tmp_path / "README.md")
    monkeypatch.setattr(port, "PORTS_DOC", tmp_path / "docs" / "ports.md")


@pytest.mark.parametrize("change", ["stale", "missing", "model"])
def test_check_fails_when_a_memory_role_is_stale(tmp_path, monkeypatch, capsys, change):
    _fake_repo(tmp_path, monkeypatch)
    role = tmp_path / "plugins" / "memory" / "codex-agents" / "memory-curator.toml"
    if change == "stale":
        role.write_text(role.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    elif change == "missing":
        role.unlink()
    else:
        role.write_text(
            re.sub(
                r'(?m)^model = ".*"$', 'model = "other-model"', role.read_text(encoding="utf-8")
            ),
            encoding="utf-8",
        )
    assert port.main(["--check"]) == 1
    assert "memory-curator.toml" in capsys.readouterr().out
