"""Fixtures for scripts/validate.py: a minimal repository that passes every check except `check_ports`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import validate  # noqa: E402

SKILL = "demo-skill"
EXTRA_AGENT = "demo-reviewer"  # a non-worker agent, so it needs a command
MEMORY_SKILL = "memo-skill"  # the second plugin: its agent has no command and is no worker
MEMORY_AGENT = "memo-agent"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def agent_text(name: str, worker: bool) -> str:
    desc = f"Runs the {name} job. " + ("Use proactively when delegating it." if worker else "Use when asked for it.")
    turns = "maxTurns: 10\n" if worker else ""
    return f"---\nname: {name}\ndescription: {desc}\ntools: [Read, Grep]\neffort: low\nmodel: haiku\n{turns}---\nBody.\n"


def command_text(body: str) -> str:
    return f'---\ndescription: A command.\ndisable-model-invocation: true\nargument-hint: "[task]"\n---\n{body} $ARGUMENTS\n'


def write_evals(plugin: Path) -> None:
    """One trigger grader, one no-trigger grader naming everything, one with-policy case embedding the policy."""
    evals = plugin / "evals"
    skills = SKILL
    agents = "|".join([*sorted(validate.WORKERS), EXTRA_AGENT])
    head = "---\ntype: regex\ntarget: trace\n"
    write(evals / "trigger" / SKILL / "graders" / "fired.md", f"{head}pattern: '\\\"skill\\W{{1,8}}(agent-skills:)?{SKILL}\\b'\n---\n")
    write(
        evals / "no-trigger" / "neg-demo" / "graders" / "silent.md",
        f"{head}match: not_contains\npattern: '\\\"skill\\W{{1,8}}(agent-skills:)?({skills})\\b|subagent_type\\W{{1,8}}(agent-skills:)?({agents})\\b'\n---\n",
    )
    write(
        evals / "offload" / "summarizer-with-policy" / "case.yaml",
        "name: offload-summarizer-with-policy\nexecution:\n  append_system_prompt: |\n    x\n",
    )


def build_mini_repo(root: Path) -> None:
    plugin = root / "plugins" / "agent-skills"
    write(
        plugin / "skills" / SKILL / "SKILL.md",
        f"---\nname: {SKILL}\ndescription: Explains the demo. Use when a demo is needed.\n---\nBody.\n",
    )
    for name in sorted(validate.WORKERS):
        write(plugin / "agents" / f"{name}.md", agent_text(name, worker=True))
    write(plugin / "agents" / f"{EXTRA_AGENT}.md", agent_text(EXTRA_AGENT, worker=False))
    offload = "\n".join(f"| agent-skills:{name} |" for name in sorted(validate.WORKERS))
    write(plugin / "commands" / "offload.md", command_text(f"Offload table:\n{offload}\n"))
    write(plugin / "commands" / f"{EXTRA_AGENT}.md", command_text(f"Run agent-skills:{EXTRA_AGENT} on"))
    write(plugin / ".claude-plugin" / "plugin.json", json.dumps({"name": "agent-skills", "version": "1.0.0"}))
    write(plugin / "CHANGELOG.md", "# Changelog\n\n## [1.0.0] - 2026-01-01\n\n- First release.\n")

    write_evals(plugin)

    memory = root / "plugins" / "memory"
    write(
        memory / "skills" / MEMORY_SKILL / "SKILL.md",
        f"---\nname: {MEMORY_SKILL}\ndescription: Keeps notes. Use when a note is needed.\n---\nBody.\n",
    )
    write(memory / "agents" / f"{MEMORY_AGENT}.md", agent_text(MEMORY_AGENT, worker=False).replace("---\nBody", f"skills: [{MEMORY_SKILL}]\n---\nBody"))
    write(memory / ".claude-plugin" / "plugin.json", json.dumps({"name": "memory", "version": "1.0.0"}))
    write(memory / "CHANGELOG.md", "# Changelog\n\n## [1.0.0] - 2026-01-01\n\n- First release.\n")

    entry = {"plugins": [{"name": "agent-skills", "source": "./plugins/agent-skills"}]}
    for rel in validate.CATALOGS:
        write(root / rel, json.dumps(entry))
    for rel in ("user-config/offload-policy.md", "user-config/routing.md", "user-agents/Explore.md", "LICENSE"):
        write(root / rel, "x\n")

    agents = "\n".join(
        f"| `{n}` | haiku | — | does it |" for n in [*sorted(validate.WORKERS), EXTRA_AGENT]
    )
    commands = "\n".join(f"| `/agent-skills:{n}` | does it |" for n in ["offload", EXTRA_AGENT])
    write(
        root / "README.md",
        "# Demo\n\n"
        "## Install\n\n## Update\n\n## Develop\n\n## Recommended prompt\n\n"
        f"## Catalog\n\n### Agents\n\n| Agent | Model | Preloads | Purpose |\n|---|---|---|---|\n{agents}\n\n"
        f"### Skills\n\n| Skill | Purpose |\n|---|---|\n| `{SKILL}` | does it |\n\n"
        f"### Commands\n\n| Command | Purpose |\n|---|---|\n{commands}\n",
    )


@pytest.fixture
def mini_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a minimal valid repository and point every path global of `validate` at it."""
    build_mini_repo(tmp_path)
    plugin = tmp_path / "plugins" / "agent-skills"
    monkeypatch.setattr(validate, "ROOT", tmp_path)
    monkeypatch.setattr(validate, "PLUGIN", plugin)
    monkeypatch.setattr(validate, "POLICY", tmp_path / "user-config" / "offload-policy.md")
    monkeypatch.setattr(validate, "OFFLOAD_COMMAND", plugin / "commands" / "offload.md")
    return tmp_path


def run_checks(root: Path) -> list[str]:
    """Errors of every check except `check_ports` and the `--release` git checks (`root` documents the target)."""
    assert validate.ROOT == root, "patch validate.ROOT with the mini_repo fixture first"
    errors: list[str] = []
    skills: set[str] = set()
    agents: set[str] = set()
    for plugin in validate.plugin_dirs():
        plugin_skills = validate.check_skills(errors, plugin)
        plugin_agents = validate.check_agents(errors, plugin_skills, plugin)
        if plugin == validate.PLUGIN:
            skills, agents = plugin_skills, plugin_agents
    validate.check_commands(errors, skills, agents)
    validate.check_eval_graders(errors, skills, agents)
    validate.check_offload_policy(errors)
    validate.check_readme_catalog(errors)
    validate.check_public_paths(errors)
    validate.check_versions(errors, release=False)
    return errors
