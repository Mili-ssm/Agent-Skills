#!/usr/bin/env python3
"""Generate the GitHub Copilot CLI and OpenAI Codex ports of the agent-skills plugin (ADR 0015, docs/ports.md).

  python3 scripts/port.py            write ports/, both catalogs and both policy variants
  python3 scripts/port.py --check    prove the copies are current and equivalent to the Claude sources
  python3 scripts/port.py --report   print what each artifact type maps to and what does not map

The Claude sources (plugins/, .claude-plugin/, user-config/offload-policy.md) are only read, except one output:
plugins/agent-skills/hooks/offload-policy.md, the copy the session start hook prints (an installed hook reads
only files under its plugin root). Claude Code behaves as before otherwise. No CLAUDE.md or AGENTS.md is generated (Claude Code would load it).

Standard library only (Python 3.11+, tomllib). Exit code 0 = ok, 1 = errors (printed one per line).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, Unpack

from promptkit.fragments import FragmentError, strip_markers
from promptkit.models import CATALOG, derive_pairs, load_catalog
from validate import FrontmatterError, as_list, check_agent_rules, is_true, parse_frontmatter

if TYPE_CHECKING:
    from promptkit.models import Catalog

# Repo root = parent of scripts/, independent of the current working directory.
ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "agent-skills"
CLAUDE_MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
POLICY = ROOT / "user-config" / "offload-policy.md"
ROUTING = ROOT / "user-config" / "routing.md"
README = ROOT / "README.md"
README_REL = "README.md"
HOOK_POLICY_REL = "plugins/agent-skills/hooks/offload-policy.md"
# README block filled by this script: the recommended prompt (offload policy + routing) per tool.
PROMPT_BEGIN = "<!-- BEGIN generated: recommended-prompt -->"
PROMPT_END = "<!-- END generated: recommended-prompt -->"
# docs/ports.md block filled by this script: the model catalog and the derived Codex pairs.
PORTS_DOC = ROOT / "docs" / "ports.md"
PORTS_DOC_REL = "docs/ports.md"
MODELS_BEGIN = "<!-- BEGIN generated: models -->"
MODELS_END = "<!-- END generated: models -->"
PORTS = "ports"

# Catalog name shared with .claude-plugin/marketplace.json; it is part of every install path (checked on load).
MARKETPLACE = "mili-ssm"
# The one plugin that is ported; the mods are Claude-only (no mods API elsewhere).
PLUGIN_NAME = "agent-skills"

CATALOG_DATA = load_catalog(CATALOG)
# Copilot runs the same Claude models, so model and effort pass through unchanged; the ids live in the catalog.
# A model without an id is left out; check_agent reports it.
COPILOT_MODELS = {m.key: m.copilot for m in CATALOG_DATA.models("claude") if m.copilot}
# Claude (model, effort) -> Codex (model, effort), derived from shared/models.toml (levels, costs, effort policy and
# the Haiku medium pin; ADR 0017). A pair missing here is an error in --check.
CODEX_PAIRS: dict[tuple[str, str], tuple[str, str]] = derive_pairs(CATALOG_DATA, "claude", "codex")
# Text like "(Sonnet)" names a model, not an agent; it is rewritten with the model of the pair most agents use.
CODEX_LABEL_EFFORT = {"haiku": "medium", "sonnet": "medium", "opus": "high"}
MODEL_MAP = {"copilot": COPILOT_MODELS}


def codex_label_model(tier: str) -> str:
    """The Codex model that replaces the Claude name "(Haiku)", "(Sonnet)" or "(Opus)" in text."""
    return CODEX_PAIRS[tier, CODEX_LABEL_EFFORT[tier]][0]


# Where Copilot CLI installs plugins; the shell expands the variables inside the commands the skills print.
COPILOT_BASE = "${COPILOT_HOME:-$HOME/.copilot}/installed-plugins"
COPILOT_ROOT = f"{COPILOT_BASE}/{MARKETPLACE}/{PLUGIN_NAME}"
# Where Codex caches a plugin; its manifest has no `version`, so the cache folder is `local`.
CODEX_BASE = "${CODEX_HOME:-$HOME/.codex}/plugins/cache"
CODEX_ROOT = f"{CODEX_BASE}/{MARKETPLACE}/{PLUGIN_NAME}/local"
# Claude tool -> Copilot tool alias; None drops the tool because Copilot exposes skills without a tool.
TOOL_MAP: dict[str, str | None] = {
    "Read": "read",
    "Grep": "search",
    "Glob": "search",
    "Bash": "execute",
    "Edit": "edit",
    "Write": "edit",
    "NotebookEdit": "edit",
    "WebSearch": "web",
    "WebFetch": "web",
    "Skill": None,
    "Monitor": None,
    "mcp__fff__grep": None,
    "mcp__fff__find_files": None,
    "mcp__fff__multi_grep": None,
}
# Frontmatter fields the generator knows how to port; any other field stops it instead of being dropped silently.
SKILL_FIELDS = {"name", "description"}
AGENT_FIELDS = {
    "name",
    "description",
    "tools",
    "disallowedTools",
    "model",
    "effort",
    "maxTurns",
    "omitClaudeMd",
    "skills",
}
COMMAND_FIELDS = {"description", "argument-hint", "disable-model-invocation"}
# Codex rejects unknown keys in a role file, so only these may be emitted (features: shell_tool only).
CODEX_ROLE_KEYS = {
    "name",
    "description",
    "developer_instructions",
    "model",
    "model_reasoning_effort",
    "features",
}
# Tools whose removal makes an agent read-only; Codex cannot enforce it, so the agent is told.
WRITE_TOOLS = {"Edit", "Write"}
# Variables and paths that mean something only inside Claude Code; none may survive in an instruction file.
SKILL_DIR_VAR = "${CLAUDE_SKILL_DIR}"
PLUGIN_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"
CLAUDE_PLUGINS = "~/.claude/plugins"
CLAUDE_ONLY_TOKENS = ("${CLAUDE_", "~/.claude/", "`AskUserQuestion`", "`Explore`")
# `agent-skills:<name>`; the whole name is matched so `architect` never cuts into `architecture-principles`.
PLUGIN_REF = re.compile(r"(?<![\w-])agent-skills:([a-z0-9-]+)(?!\w)")
# Neither tool substitutes $ARGUMENTS, so the model is told where the user's words are.
ARGUMENTS_TEXT = "<the arguments the user gave with this command; empty if none>"
# Claude's interview tool has no fixed name elsewhere, so the text names the capability instead.
ASK_USER_TEXT = "your tool for asking the user questions (or a direct question in chat)"
# Claude model names written as "(Haiku)"; Codex runs other models, so the text names its tier instead.
MODEL_LABELS = {"haiku": "Haiku", "sonnet": "Sonnet", "opus": "Opus"}
# Agent bodies point to Claude's CLAUDE.md for delegation rules; each tool reads other instruction files.
DELEGATION_RULE = "Delegation rules in CLAUDE.md"
# Claude states a preloaded skill's base directory; without it relative links resolve against the project.
BASE_DIR_LINE = (
    "Base directory for this skill: `{root}/skills/{skill}`; "
    "resolve its relative links (`references/…`, `scripts/…`) there."
)
# Codex has no tool names to allow, so the rule lists what each Claude tool lets the agent do.
# None: a Claude-only tool (an optional MCP server, ADR 0024, or `Monitor`, ADR 0025); the Codex tools rule leaves it out.
TOOL_CAPABILITY: dict[str, str | None] = {
    "Read": "read files",
    "Grep": "search file contents",
    "Glob": "find files by name",
    "Bash": "shell commands",
    "Edit": "edit files",
    "Write": "create files",
    "NotebookEdit": "edit notebooks",
    "WebSearch": "web search",
    "WebFetch": "fetch web pages",
    "Skill": "use skills",
    "Monitor": None,
    "mcp__fff__grep": None,
    "mcp__fff__find_files": None,
    "mcp__fff__multi_grep": None,
}
# Command lines that state Claude-only facts; the ports drop them instead of carrying a false claim.
CLAUDE_ONLY_LINE = re.compile(
    r"^- `Explore` runs on Haiku only with the user-scope override.*(?:\n|\Z)",
    re.MULTILINE,
)
# Codex's equivalent of Claude's disable-model-invocation: the skill runs only when the user names it.
OPENAI_YAML = "policy:\n  allow_implicit_invocation: false\n"
AGENT_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
POLICY_BANNER = "<!-- Generated by scripts/port.py from offload-policy.md; edit that file. -->"
ROUTING_BANNER = "<!-- Generated by scripts/port.py from routing.md; edit that file. -->"
READ_ONLY_RULE = (
    "## Read-only\n\nLeave the project's files unchanged: do not use apply_patch or any "
    "edit tool, and run only commands that do not change them (temp dirs and build "
    "caches are fine). Claude Code enforces this; Codex does not, so it is your rule."
)
CATALOG_DESCRIPTION = (
    "agent-skills for {label}: specialist skills and agents generated from the "
    "Claude Code plugin (scripts/port.py)."
)


# Codex has no background dispatch flag, no `Monitor` and no per-call shell timeout parameter, and reads AGENTS.md.
# Claude source text -> Codex text, keyed by the source file (`:description` for a frontmatter description).
# Every old text must occur in its file, or the port fails: a source edit must not leave a false claim behind.
CODEX_REWRITES: dict[str, tuple[tuple[str, str], ...]] = {
    "user-config/offload-policy.md": (
        (
            "(in the background while you keep working)",
            "(spawn it, keep working, and collect its result before your final answer)",
        ),
        (
            "Run it in the background with the checks,",
            "Spawn it together with the checks and collect its result before your final answer,",
        ),
    ),
    "user-config/routing.md": (
        (
            "The owner's manual entries to the same skills and agents (slash commands in Claude Code) never auto-trigger",
            "The owner's manual skill mentions (`$name`) never auto-trigger",
        ),
        ("agent definition or CLAUDE.md", "agent definition or AGENTS.md"),
        (
            "dispatched with no model parameter: the agent file fixes its model,",
            "dispatched without overriding its model or effort: the agent's TOML fixes both,",
        ),
        (
            "also with no model parameter, which replaces",
            "also without overriding its model or effort (its TOML fixes both), which replaces",
        ),
    ),
    "agents/check-runner.md:description": (
        (
            "in the background when the main conversation can keep working meanwhile",
            "so the main conversation can keep working meanwhile",
        ),
    ),
    "agents/skeptical-reviewer.md:description": (
        (
            "run in the background with check-runner,",
            "run with check-runner while the main conversation keeps working,",
        ),
    ),
    "agents/check-runner.md": (
        (
            (
                "Set the Bash `timeout` parameter (milliseconds) to the same limit, because its default is 2 minutes and its maximum 10; "
                "a command that cannot finish within that maximum goes under `Not run:`. "
                "When the harness moves a command to the background, wait for it with `Monitor` (a condition on its output file), never `sleep`."
            ),
            (
                "Put the limit in the command itself (`timeout 300 <cmd>`), because the shell tool's own limit may be shorter; "
                "a command that cannot finish within 10 minutes goes under `Not run:`. "
                "To wait for a slow command, poll by rerunning a short check on its output instead of one long `sleep`."
            ),
        ),
    ),
    "agents/ui-verifier.md": (
        (
            "in one Bash call with the `timeout` parameter set to 5\u20139 minutes (300000\u2013540000 ms), because the 2-minute default would kill it, and because",
            "in one shell call wrapped in `timeout 540`, because a browser run can take minutes, and because",
        ),
        (
            "Use `Monitor` only to wait for a command the harness moved to the background, never `sleep`.",
            "To wait for a slow command, poll by rerunning a short check instead of one long `sleep`.",
        ),
    ),
    "agents/implementer.md": (
        (
            "with the shell tool's timeout set to its expected duration (in Claude Code the Bash `timeout` parameter, at most 10 minutes)",
            "with a time limit in the command itself (`timeout 600 <cmd>`, at most 10 minutes)",
        ),
        (
            (
                "When the harness moves a command to the background, wait for it with the waiting tool the harness names "
                "(in Claude Code, `Monitor` with a condition on its output file), never with `sleep`, which Claude Code blocks."
            ),
            "To wait for a slow command, poll by rerunning a short check on its output instead of one long `sleep`.",
        ),
    ),
    "commands/offload.md": (
        (
            "Long runs go in the background, so this conversation keeps working",
            "Long runs are spawned as subagents, so this conversation keeps working",
        ),
    ),
}


@dataclass(frozen=True)
class Target:
    """One tool the plugin is ported to."""

    key: str  # "copilot" | "codex"
    label: str
    dir: str  # plugin folder, relative to the repo root
    root: str  # where the tool installs the plugin
    base: str  # where the tool installs all plugins
    catalog: str  # marketplace file in the tool's own lookup path
    policy: str  # offload policy variant
    explore: str  # what the built-in explorer is called in this tool
    delegation: str  # where this tool reads delegation rules
    routing: str  # routing table variant


COPILOT = Target(
    "copilot",
    "GitHub Copilot CLI",
    f"{PORTS}/copilot/{PLUGIN_NAME}",
    COPILOT_ROOT,
    COPILOT_BASE,
    ".github/plugin/marketplace.json",
    "user-config/offload-policy.copilot.md",
    "`explore` (built-in agent)",
    "Delegation rules in your instruction files (copilot-instructions.md, AGENTS.md)",
    "user-config/routing.copilot.md",
)
CODEX = Target(
    "codex",
    "OpenAI Codex",
    f"{PORTS}/codex/{PLUGIN_NAME}",
    CODEX_ROOT,
    CODEX_BASE,
    ".agents/plugins/marketplace.json",
    "user-config/offload-policy.codex.md",
    "`explorer` (built-in role)",
    "Delegation rules in AGENTS.md",
    "user-config/routing.codex.md",
)
TARGETS = (COPILOT, CODEX)
# Plugins a catalog lists beside agent-skills, served from their source folder with no generated copy (ADR 0036).
SOURCE_PLUGINS: dict[str, dict[str, str]] = {"codex": {"memory": "plugins/memory"}}
# Where the Codex roles of a source plugin are generated: inside the plugin, because Codex's plugin cache holds only
# that folder (the Claude plugin loads agents/*.md only, so these .toml files are inert for it).
ROLES_DIR = "codex-agents"


def role_dirs() -> list[str]:
    """Folders of generated Codex roles inside source plugins."""
    return [f"{folder}/{ROLES_DIR}" for folder in SOURCE_PLUGINS["codex"].values()]


def catalog_plugins(target: Target) -> list[tuple[str, str]]:
    """(name, folder) of each plugin the target's catalog lists, in order."""
    return [(PLUGIN_NAME, target.dir), *SOURCE_PLUGINS.get(target.key, {}).items()]


class PortError(Exception):
    """A source that cannot be ported faithfully."""


@dataclass(frozen=True)
class Doc:
    """A Claude source file: raw frontmatter fields plus the body below them."""

    name: str
    path: Path
    text: str
    fm: dict
    body: str


@dataclass(frozen=True)
class Sources:
    """Everything the ports are generated from."""

    plugin: dict
    marketplace: dict
    policy: str
    routing: str
    skills: dict[str, Doc]
    agents: dict[str, Doc]
    commands: dict[str, Doc]
    # Agents of the `SOURCE_PLUGINS` plugins, keyed by plugin name: only Codex roles are generated from them.
    source_agents: dict[str, dict[str, Doc]] = field(default_factory=dict)


@dataclass(frozen=True)
class Blob:
    """A generated file: bytes plus the executable bit (copied scripts keep it)."""

    data: bytes
    executable: bool = False


# --- reading the Claude sources -------------------------------------------------------------


def body_of(text: str) -> str:
    """The text below the closing frontmatter fence, without surrounding blank lines."""
    return text[text.find("\n---", 4) + 4 :].strip("\n")


def load_docs(
    pattern: str,
    allowed: set[str],
    required: tuple[str, ...],
    errors: list[str],
    base: Path | None = None,
) -> dict[str, Doc]:
    """Read every Markdown source matching `pattern` under `base` (default: agent-skills); unknown or missing frontmatter fields are errors."""
    docs: dict[str, Doc] = {}
    for path in sorted((base or PLUGIN).glob(pattern)):
        rel = path.relative_to(ROOT)
        name = path.parent.name if path.name == "SKILL.md" else path.stem
        text = path.read_text(encoding="utf-8")
        try:
            fm = parse_frontmatter(text)
        except FrontmatterError as exc:
            errors.append(f"{rel}: {exc}")
            continue
        errors.extend(
            f"{rel}: frontmatter field '{key}' has no mapping; extend scripts/port.py first"
            for key in sorted(set(fm) - allowed)
        )
        errors.extend(f"{rel}: missing '{key}'" for key in required if not fm.get(key))
        if "name" in allowed and fm.get("name") != name:
            errors.append(f"{rel}: frontmatter name must be '{name}'")
        docs[name] = Doc(name, path, text, fm, body_of(text))
    return docs


def agent_tools(fm: dict) -> list[str]:
    """Claude tools an agent holds: `tools` minus `disallowedTools`, in source order."""
    blocked = set(as_list(fm.get("disallowedTools")))
    return [tool for tool in as_list(fm.get("tools")) if tool not in blocked]


def codex_capabilities(fm: dict) -> str:
    """The capabilities the Codex tools rule lists for an agent (optional MCP tools left out)."""
    return ", ".join(c for t in agent_tools(fm) if (c := TOOL_CAPABILITY[t]))


def needs_codex_shell(fm: dict) -> bool:
    """Codex reads and searches files through its shell, so only an agent without any of these may lose it."""
    return bool({"Bash", "Read", "Grep", "Glob"} & set(agent_tools(fm)))


def copilot_tools(fm: dict) -> list[str]:
    """Copilot tool aliases for an agent: mapped, deduplicated, in source order (Skill dropped)."""
    mapped: list[str] = []
    for tool in agent_tools(fm):
        alias = TOOL_MAP.get(tool)
        if alias and alias not in mapped:
            mapped.append(alias)
    return mapped


def _agent_model_errors(fm: dict, rel: object) -> list[str]:
    """Model and (model, effort) values the Copilot and Codex mappings do not cover."""
    errors: list[str] = []
    if fm.get("model") not in MODEL_MAP["copilot"]:
        errors.append(f"{rel}: model {fm.get('model')!r} is not in MODEL_MAP")
    if (fm.get("model"), fm.get("effort")) not in CODEX_PAIRS:
        errors.append(
            f"{rel}: (model, effort) {(fm.get('model'), fm.get('effort'))!r} is not in CODEX_PAIRS"
        )
    return errors


def _agent_tool_errors(fm: dict, rel: object) -> list[str]:
    """Tools without a mapping, and blocked tools whose Copilot alias another tool keeps granted."""
    errors = [
        f"{rel}: tool '{tool}' is not in TOOL_MAP and TOOL_CAPABILITY"
        for tool in as_list(fm.get("tools"))
        if tool not in TOOL_MAP or tool not in TOOL_CAPABILITY
    ]
    if not copilot_tools(fm):
        errors.append(f"{rel}: no tool maps to a Copilot tool")
    # Edit and Write share one Copilot alias: a blocked tool whose alias another tool keeps cannot be enforced.
    kept = set(copilot_tools(fm))
    errors.extend(
        f"{rel}: '{tool}' is disallowed but Copilot alias '{TOOL_MAP[tool]}' stays granted"
        for tool in as_list(fm.get("disallowedTools"))
        if TOOL_MAP.get(tool) in kept
    )
    return errors


def check_agent(doc: Doc, skills: dict[str, Doc], errors: list[str]) -> None:
    """Report agent values the tool mappings do not cover, instead of porting a guess."""
    fm, rel = doc.fm, doc.path.relative_to(ROOT)
    check_agent_rules(rel, fm, set(skills), errors)
    errors.extend(_agent_model_errors(fm, rel))
    errors.extend(_agent_tool_errors(fm, rel))


def _manifest_errors(plugin: dict, marketplace: dict) -> list[str]:
    """Problems in the plugin manifest and the marketplace entry the ports are built from."""
    errors: list[str] = []
    if marketplace.get("name") != MARKETPLACE:
        errors.append(
            f".claude-plugin/marketplace.json: name is {marketplace.get('name')!r}; MARKETPLACE says {MARKETPLACE!r}"
        )
    if plugin.get("name") != PLUGIN_NAME:
        errors.append(
            f"plugin.json: name is {plugin.get('name')!r}; PLUGIN_NAME says {PLUGIN_NAME!r}"
        )
    errors.extend(
        f"plugins/{PLUGIN_NAME}/.claude-plugin/plugin.json: missing '{key}'"
        for key in ("version", "description", "author", "repository")
        if not plugin.get(key)
    )
    if not (marketplace.get("owner") or {}).get("name"):
        errors.append(".claude-plugin/marketplace.json: missing owner.name")
    return errors


def _command_errors(commands: dict[str, Doc], skills: dict[str, Doc]) -> list[str]:
    """Commands that collide with a skill name or stay open to model invocation."""
    errors: list[str] = []
    for name, doc in commands.items():
        rel = doc.path.relative_to(ROOT)
        if name in skills:
            errors.append(f"{rel}: command '{name}' collides with the skill of the same name")
        if not is_true(doc.fm.get("disable-model-invocation")):
            errors.append(f"{rel}: commands must set disable-model-invocation: true")
    return errors


def _source_agents(errors: list[str]) -> dict[str, dict[str, Doc]]:
    """The agents of each `SOURCE_PLUGINS` plugin, checked like the agent-skills ones (they preload no skill)."""
    found: dict[str, dict[str, Doc]] = {}
    for plugin, folder in SOURCE_PLUGINS["codex"].items():
        docs = load_docs(
            "agents/*.md",
            AGENT_FIELDS,
            ("name", "description", "tools", "model", "effort"),
            errors,
            ROOT / folder,
        )
        for doc in docs.values():
            check_agent(doc, {}, errors)
        found[plugin] = docs
    return found


def load_sources() -> tuple[Sources, list[str]]:
    """Read the plugin, marketplace, policy, skills, agents and commands, with every problem found."""
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads(CLAUDE_MARKETPLACE.read_text(encoding="utf-8"))
    errors = _manifest_errors(plugin, marketplace)
    skills = load_docs("skills/*/SKILL.md", SKILL_FIELDS, ("name", "description"), errors)
    agents = load_docs(
        "agents/*.md",
        AGENT_FIELDS,
        ("name", "description", "tools", "model", "effort"),
        errors,
    )
    commands = load_docs("commands/*.md", COMMAND_FIELDS, ("description", "argument-hint"), errors)
    for doc in agents.values():
        check_agent(doc, skills, errors)
    source_agents = _source_agents(errors)
    errors.extend(_command_errors(commands, skills))
    return Sources(
        plugin,
        marketplace,
        POLICY.read_text(encoding="utf-8"),
        ROUTING.read_text(encoding="utf-8"),
        skills,
        agents,
        commands,
        source_agents,
    ), errors


# --- text transforms --------------------------------------------------------------------------


def rename_agents(text: str, agents: set[str]) -> str:
    """Transform 2: `agent-skills:<agent>` -> `<agent>`; skills and commands keep their namespace."""
    return PLUGIN_REF.sub(lambda m: m.group(1) if m.group(1) in agents else m.group(0), text)


class FileKind(TypedDict, total=False):
    """What kind of file a text belongs to: which transforms beyond the common ones it needs."""

    skill: str | None  # the skill folder name, for ${CLAUDE_SKILL_DIR}
    command: bool
    agent: bool
    rewrites: str  # key into CODEX_REWRITES: the source file the text comes from


def codex_rewrite(text: str, key: str | None) -> str:
    """Swap the Claude-only wording of one source file for Codex's; a missing source text is an error."""
    for old, new in CODEX_REWRITES.get(key or "", ()):
        if old not in text:
            raise PortError(f"Codex rewrite source text not found: {old[:70]!r}")
        text = text.replace(old, new)
    return text


def _resolve_paths(text: str, target: Target, skill: str | None) -> str:
    """Point the plugin variables and the Claude plugin folder at the tool's install paths."""
    if SKILL_DIR_VAR in text:
        if skill is None:
            raise PortError(f"{SKILL_DIR_VAR} outside a skill has no folder to point to")
        text = text.replace(SKILL_DIR_VAR, f"{target.root}/skills/{skill}")
    return text.replace(PLUGIN_ROOT_VAR, target.root).replace(CLAUDE_PLUGINS, target.base)


def _apply_kind(text: str, target: Target, kind: FileKind) -> str:
    """The transforms only commands (`$ARGUMENTS`, Claude-only lines) and agents (delegation rule) need."""
    if kind.get("command"):
        text = CLAUDE_ONLY_LINE.sub("", text).replace("$ARGUMENTS", ARGUMENTS_TEXT)
    if kind.get("agent"):
        text = text.replace(DELEGATION_RULE, target.delegation)
    return text


def transform(text: str, target: Target, agents: set[str], **kind: Unpack[FileKind]) -> str:
    """All text transforms for one tool; `command` and `agent` add the ones only those files need."""
    text = strip_markers(text)
    if target is CODEX:
        text = codex_rewrite(text, kind.get("rewrites"))
    text = _resolve_paths(text, target, kind.get("skill"))
    if target is COPILOT:  # Copilot invokes plugin skills by their bare name
        text = text.replace("/agent-skills:", "/")
    text = _apply_kind(rename_agents(text, agents), target, kind)
    text = text.replace("`Explore`", target.explore)
    text = text.replace("`AskUserQuestion`", ASK_USER_TEXT)
    if target is CODEX:
        for tier, label in MODEL_LABELS.items():
            text = text.replace(f"({label})", f"({codex_label_model(tier)})")
    return text


def q(value: str) -> str:
    """A double-quoted string that is valid JSON, YAML and TOML, so colons, quotes and brackets are safe."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def toml_multiline(text: str) -> str:
    """A TOML multi-line literal string; an escaped basic string when the text cannot sit in one."""
    plain = all(c in "\n\t" or (c >= " " and c != "\x7f") for c in text)
    if plain and "'''" not in text and text.endswith("\n"):
        return f"'''\n{text}'''"
    return q(text)


def frontmatter(pairs: list[tuple[str, str]]) -> str:
    """A frontmatter block from (key, already formatted value) pairs."""
    return "---\n" + "".join(f"{key}: {value}\n" for key, value in pairs) + "---\n"


def dumps_json(data: object) -> str:
    """A JSON file: two-space indent, keys in insertion order, trailing newline."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def source_files(folder: Path) -> list[Path]:
    """Files of a skill folder to port: everything except bytecode caches."""
    return [
        p
        for p in sorted(folder.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    ]


def skill_file_bytes(path: Path) -> bytes:
    """A skill file as the ports carry it: Markdown loses its shared-block markers, other files stay byte-exact."""
    data = path.read_bytes()
    if path.suffix != ".md":
        return data
    return strip_markers(data.decode("utf-8")).encode("utf-8")


def is_executable(path: Path) -> bool:
    """Whether any execute bit is set."""
    return bool(path.stat().st_mode & 0o111)


def stale_token(text: str, target: Target) -> str | None:
    """The first token left in an instruction file that is Claude-only for `target`, if any."""
    own = ["/agent-skills:"] if target is COPILOT else [f"({m})" for m in MODEL_LABELS.values()]
    return next((t for t in (*CLAUDE_ONLY_TOKENS, *own) if t in text), None)


# --- generation -------------------------------------------------------------------------------


class Generator:
    """Builds every generated file in memory; problems are collected, not raised."""

    def __init__(self, src: Sources) -> None:
        self.src = src
        self.agents = set(src.agents)
        self.files: dict[str, Blob] = {}
        self.errors: list[str] = []

    def t(
        self,
        text: str,
        target: Target,
        where: str,
        **kind: Unpack[FileKind],
    ) -> str:
        """`transform` that records a failure against `where` instead of raising."""
        kind["rewrites"] = where
        try:
            return transform(text, target, self.agents, **kind)
        except (PortError, FragmentError) as exc:
            self.errors.append(f"{where}: {exc}")
            return text

    def put(self, rel: str, content: str | bytes, *, executable: bool = False) -> None:
        """Add one generated file."""
        if rel in self.files:
            self.errors.append(f"{rel}: generated twice")
            return
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.files[rel] = Blob(data, executable)

    def put_instruction(self, rel: str, text: str, target: Target) -> None:
        """Add a file the tool reads as instructions; Claude-only tokens must not survive in it."""
        found = stale_token(text, target)
        if found:
            self.errors.append(f"{rel}: still contains the Claude-only token '{found}'")
        self.put(rel, text)

    def manifest(self, target: Target) -> None:
        """The plugin manifest in the tool's own format."""
        plugin = self.src.plugin
        if target is COPILOT:
            data = {
                "$schema": AGENT_PLUGIN_SCHEMA,
                "name": PLUGIN_NAME,
                "version": plugin["version"],
                "description": plugin["description"],
                "author": plugin["author"],
                "repository": plugin["repository"],
            }
            self.put(f"{target.dir}/plugin.json", dumps_json(data))
        else:
            # No version on purpose: Codex caches an unversioned plugin under `local`, which CODEX_ROOT and the skills' printed paths rely on.
            data = {
                "name": PLUGIN_NAME,
                "description": plugin["description"],
                "skills": "./skills",
            }
            self.put(f"{target.dir}/.codex-plugin/plugin.json", dumps_json(data))

    def skills(self, target: Target) -> None:
        """Copy each skill folder; only SKILL.md is transformed (references/ and scripts/ are content)."""
        for name, doc in self.src.skills.items():
            for path in source_files(doc.path.parent):
                inside = path.relative_to(doc.path.parent).as_posix()
                dest = f"{target.dir}/skills/{name}/{inside}"
                if inside == "SKILL.md":
                    text = self.t(doc.text, target, f"skills/{name}/SKILL.md", skill=name)
                    self.put_instruction(dest, text, target)
                else:
                    self.put(dest, skill_file_bytes(path), executable=is_executable(path))

    def commands(self, target: Target) -> None:
        """Commands become user-only skills: neither tool runs Claude command files."""
        for name, doc in self.src.commands.items():
            where = f"commands/{name}.md"
            body = self.t(doc.body, target, where, command=True)
            description = q(self.t(doc.fm["description"], target, f"{where}:description"))
            dest = f"{target.dir}/skills/{name}"
            if target is COPILOT:
                pairs = [
                    ("name", q(name)),
                    ("description", description),
                    ("argument-hint", q(doc.fm["argument-hint"])),
                    ("disable-model-invocation", "true"),
                ]
                self.put_instruction(f"{dest}/SKILL.md", f"{frontmatter(pairs)}\n{body}\n", target)
            else:
                pairs = [("name", q(name)), ("description", description)]
                hint = f"Arguments hint: {doc.fm['argument-hint']}"
                self.put_instruction(
                    f"{dest}/SKILL.md",
                    f"{frontmatter(pairs)}\n{hint}\n\n{body}\n",
                    target,
                )
                self.put(f"{dest}/agents/openai.yaml", OPENAI_YAML)

    def instructions(self, doc: Doc, target: Target) -> str:
        """An agent's body, then (in this order) preloaded skills, Codex-only rules and the turn limit."""
        fm, where = doc.fm, f"agents/{doc.name}.md"
        parts = [self.t(doc.body, target, where, agent=True)]
        for skill in as_list(fm.get("skills")):
            body = self.t(
                self.src.skills[skill].body,
                target,
                f"skills/{skill}/SKILL.md",
                skill=skill,
            )
            base = BASE_DIR_LINE.format(root=target.root, skill=skill)
            parts.append(f"## Preloaded skill: {skill}\n\n{base}\n\n{body}")
        if target is CODEX:
            tools = codex_capabilities(fm)
            parts.append(
                f"## Tools\n\nUse only these tools: {tools}. "
                "Claude Code enforces this list; Codex does not, so it is your rule."
            )
            if WRITE_TOOLS & set(as_list(fm.get("disallowedTools"))):
                parts.append(READ_ONLY_RULE)
        if fm.get("maxTurns"):
            parts.append(
                f"## Turn limit\n\nStop and report what you have after {int(fm['maxTurns'])} turns. "
                "Claude Code enforces this limit; here it is your rule."
            )
        return "\n\n".join(parts) + "\n"

    def agents_for(self, target: Target) -> None:
        """One agent file per Claude agent: a Copilot .agent.md or a Codex role .toml (also for `SOURCE_PLUGINS`)."""
        for doc in self.src.agents.values():
            self.agent_file(doc, target, target.dir, f"{target.dir}/agents")
        if target is CODEX:
            for plugin, folder in SOURCE_PLUGINS["codex"].items():
                for doc in self.src.source_agents[plugin].values():
                    self.agent_file(doc, target, folder, f"{folder}/{ROLES_DIR}")

    def agent_file(self, doc: Doc, target: Target, folder: str, role_dir: str) -> None:
        """One agent's file: a Copilot .agent.md under `folder`, a Codex role .toml in `role_dir`."""
        name, fm = doc.name, doc.fm
        description = self.t(fm["description"], target, f"agents/{name}.md:description")
        instructions = self.instructions(doc, target)
        if target is COPILOT:
            model = q(COPILOT_MODELS[fm["model"]])
            pairs = [
                ("name", q(name)),
                ("description", q(description)),
                ("tools", json.dumps(copilot_tools(fm))),
                ("model", model),
                ("reasoningEffort", q(fm["effort"])),
                (
                    "include-custom-instructions",
                    "false" if is_true(fm.get("omitClaudeMd")) else "true",
                ),
            ]
            dest = f"{folder}/com.github.copilot/agents/{name}.agent.md"
            self.put_instruction(dest, f"{frontmatter(pairs)}\n{instructions}", target)
        else:
            model, effort = CODEX_PAIRS[fm["model"], fm["effort"]]
            lines = [
                f"name = {q(name)}",
                f"description = {q(description)}",
                f"developer_instructions = {toml_multiline(instructions)}",
                f"model = {q(model)}",
                f"model_reasoning_effort = {q(effort)}",
            ]
            if not needs_codex_shell(fm):
                lines += ["", "[features]", "shell_tool = false"]
            self.put_instruction(f"{role_dir}/{name}.toml", "\n".join(lines) + "\n", target)

    def catalogs(self) -> None:
        """One marketplace file per tool: agent-skills, plus the source plugins of `SOURCE_PLUGINS`."""
        plugin = self.src.plugin
        owner = self.src.marketplace["owner"]["name"]
        copilot = {
            "name": MARKETPLACE,
            "owner": {"name": owner},
            "metadata": {"description": CATALOG_DESCRIPTION.format(label=COPILOT.label)},
            "plugins": [
                {
                    "name": PLUGIN_NAME,
                    "source": COPILOT.dir,
                    "description": plugin["description"],
                }
            ],
        }
        codex = {
            "name": MARKETPLACE,
            "plugins": [
                {"name": name, "source": {"source": "local", "path": f"./{folder}"}}
                for name, folder in catalog_plugins(CODEX)
            ],
        }
        self.put(COPILOT.catalog, dumps_json(copilot))
        self.put(CODEX.catalog, dumps_json(codex))

    def policies(self) -> None:
        """The offload policy with bare agent names and the tool's own name for the built-in explorer."""
        for target in TARGETS:
            text = self.t(self.src.policy, target, "user-config/offload-policy.md")
            self.put(target.policy, f"{POLICY_BANNER}\n\n{text.rstrip(chr(10))}\n")
            text = self.t(self.src.routing, target, "user-config/routing.md")
            self.put_instruction(
                target.routing, f"{ROUTING_BANNER}\n\n{text.rstrip(chr(10))}\n", target
            )

    def hook_policy(self) -> None:
        """The offload table copy the session start hook prints, byte for byte (no banner: the hook prints it as is)."""
        self.put(HOOK_POLICY_REL, self.src.policy)

    def readme(self) -> None:
        """README.md with the recommended-prompt block regenerated (the rest is kept as is)."""
        if not README.is_file():
            self.errors.append(f"{README_REL}: missing")
            return
        old = README.read_text(encoding="utf-8")
        text = prompt_block(old, self.prompts())
        if text is None:
            self.errors.append(
                f"{README_REL}: needs one {PROMPT_BEGIN} line followed by one {PROMPT_END} line"
            )
            return
        self.put(README_REL, text)

    def ports_doc(self) -> None:
        """docs/ports.md with the models block regenerated (the rest is kept as is)."""
        if not PORTS_DOC.is_file():
            self.errors.append(f"{PORTS_DOC_REL}: missing")
            return
        text = models_block(PORTS_DOC.read_text(encoding="utf-8"), CATALOG_DATA)
        if text is None:
            self.errors.append(
                f"{PORTS_DOC_REL}: needs one {MODELS_BEGIN} line followed by one {MODELS_END} line"
            )
            return
        self.put(PORTS_DOC_REL, text)

    def prompts(self) -> list[tuple[str, str]]:
        """(tool label, offload policy + routing table in that tool's names), without banners."""
        claude = f"{self.src.policy.rstrip(chr(10))}\n\n{self.src.routing.rstrip(chr(10))}\n"
        out = [("Claude Code", claude)]
        for target in TARGETS:
            parts = [
                self.t(t, target, where).rstrip("\n")
                for t, where in (
                    (self.src.policy, "user-config/offload-policy.md"),
                    (self.src.routing, "user-config/routing.md"),
                )
            ]
            out.append((target.label, "\n\n".join(parts) + "\n"))
        return out


def prompt_block(readme: str, prompts: list[tuple[str, str]]) -> str | None:
    """`readme` with the text between the prompt markers replaced by one <details> per tool; None without markers."""
    begin, end = readme.find(PROMPT_BEGIN), readme.find(PROMPT_END)
    if (
        begin == -1
        or end < begin
        or readme.count(PROMPT_BEGIN) != 1
        or readme.count(PROMPT_END) != 1
    ):
        return None
    blocks = [
        f"<details>\n<summary>{label}</summary>\n\n````markdown\n{text}````\n\n</details>"
        for label, text in prompts
    ]
    return (
        readme[: begin + len(PROMPT_BEGIN)] + "\n\n" + "\n\n".join(blocks) + "\n\n" + readme[end:]
    )


VENDOR_LABELS = {"claude": "Claude", "codex": "Codex"}


def models_tables(catalog: Catalog) -> str:
    """Per vendor model, level and relative cost; then the derived Claude -> Codex pair table."""
    parts = []
    for vendor, label in VENDOR_LABELS.items():
        rows = [f"| {label} model | Level | Relative cost per token |", "|---|---|---|"]
        rows += [f"| `{m.key}` | {m.level:g} | {m.cost:g} |" for m in catalog.models(vendor)]
        parts.append("\n".join(rows))
    pairs = derive_pairs(catalog, "claude", "codex")
    efforts = catalog.policy.efforts
    rows = ["| Claude model | " + " | ".join(efforts) + " |", "|---|" + "---|" * len(efforts)]
    for model in catalog.models("claude"):
        cells = [" ".join((f"`{pairs[model.key, e][0]}`", pairs[model.key, e][1])) for e in efforts]
        rows.append(f"| `{model.key}` | " + " | ".join(cells) + " |")
    parts.append("\n".join(rows))
    return "\n\n".join(parts)


def models_block(doc: str, catalog: Catalog) -> str | None:
    """`doc` with the text between the models markers replaced by the catalog tables; None without markers."""
    begin, end = doc.find(MODELS_BEGIN), doc.find(MODELS_END)
    if begin == -1 or end < begin or doc.count(MODELS_BEGIN) != 1 or doc.count(MODELS_END) != 1:
        return None
    return doc[: begin + len(MODELS_BEGIN)] + "\n\n" + models_tables(catalog) + "\n\n" + doc[end:]


def generate(src: Sources) -> tuple[dict[str, Blob], list[str]]:
    """Every generated file keyed by repo-relative path, plus the problems that stopped a faithful port."""
    gen = Generator(src)
    for target in TARGETS:
        gen.manifest(target)
        gen.skills(target)
        gen.commands(target)
        gen.agents_for(target)
    gen.catalogs()
    gen.policies()
    gen.hook_policy()
    gen.readme()
    gen.ports_doc()
    return gen.files, list(dict.fromkeys(gen.errors))


# --- writing and drift ------------------------------------------------------------------------


def prune(base: Path, folder: str, files: dict[str, Blob]) -> int:
    """Delete the files under `base/folder` that are not generated, then empty folders; return the files removed."""
    removed = 0
    root = base / folder
    for path in sorted(root.rglob("*"), reverse=True) if root.is_dir() else []:
        if path.is_file() and path.relative_to(base).as_posix() not in files:
            path.unlink()
            removed += 1
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return removed


def sync(files: dict[str, Blob], base: Path) -> tuple[int, int]:
    """Make `base` hold exactly `files` under ports/ and write the single files; return (written, removed)."""
    written = 0
    for rel, blob in sorted(files.items()):
        path = base / rel
        if (
            path.is_file()
            and path.read_bytes() == blob.data
            and is_executable(path) == blob.executable
        ):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob.data)
        path.chmod(0o755 if blob.executable else 0o644)
        written += 1
    removed = sum(prune(base, folder, files) for folder in (PORTS, *role_dirs()))
    return written, removed


def drift(fresh: Path) -> list[str]:
    """Compare a freshly generated tree with the repo: missing, extra and changed files."""
    errors: list[str] = []
    generated = sorted(p for p in fresh.rglob("*") if p.is_file())
    wanted = {p.relative_to(fresh).as_posix() for p in generated}
    for path in generated:
        rel = path.relative_to(fresh).as_posix()
        disk = ROOT / rel
        if not disk.is_file():
            errors.append(f"{rel}: missing; run python3 scripts/port.py")
        elif disk.read_bytes() != path.read_bytes():
            errors.append(f"{rel}: differs from the generated version; run python3 scripts/port.py")
        elif is_executable(disk) != is_executable(path):
            errors.append(f"{rel}: executable bit differs; run python3 scripts/port.py")
    errors.extend(
        f"{p.relative_to(ROOT).as_posix()}: extra file, not generated; run python3 scripts/port.py"
        for folder in (PORTS, *role_dirs())
        for p in sorted((ROOT / folder).rglob("*"))
        if p.is_file() and p.relative_to(ROOT).as_posix() not in wanted
    )
    return errors


# --- equivalence: parse the files on disk back and compare them with the Claude sources ---------


def expected_text(text: str, target: Target, agents: set[str], **kind: Unpack[FileKind]) -> str:
    """What `text` must become for `target`, as an ordered list of swaps (independent of the generator)."""
    swaps = [
        (SKILL_DIR_VAR, f"{target.root}/skills/{kind.get('skill')}"),
        (PLUGIN_ROOT_VAR, target.root),
        (CLAUDE_PLUGINS, target.base),
    ]
    if target is COPILOT:
        swaps.append(("/agent-skills:", "/"))
    text = strip_markers(text)
    if target is CODEX:
        text = _swap_all(text, list(CODEX_REWRITES.get(kind.get("rewrites", ""), ())))
    text = _swap_all(text, swaps)
    text = _expected_agent_names(text, agents)
    if kind.get("command"):
        text = CLAUDE_ONLY_LINE.sub("", text)
    return _swap_all(text, _expected_kind_swaps(target, kind))


def _swap_all(text: str, swaps: list[tuple[str, str]]) -> str:
    """Apply the (old, new) replacements in order."""
    for old, new in swaps:
        text = text.replace(old, new)
    return text


def _expected_agent_names(text: str, agents: set[str]) -> str:
    """`agent-skills:<agent>` -> `<agent>` for the known agents, written as a split instead of a substitution."""
    pieces = re.split(r"((?<![\w-])agent-skills:[a-z0-9-]+(?!\w))", text)
    for i in range(1, len(pieces), 2):
        name = pieces[i].removeprefix("agent-skills:")
        pieces[i] = name if name in agents else pieces[i]
    return "".join(pieces)


def _expected_kind_swaps(target: Target, kind: FileKind) -> list[tuple[str, str]]:
    """The swaps applied after the agent names: command, agent, built-in names and Codex model labels."""
    swaps: list[tuple[str, str]] = []
    if kind.get("command"):
        swaps.append(("$ARGUMENTS", ARGUMENTS_TEXT))
    if kind.get("agent"):
        swaps.append((DELEGATION_RULE, target.delegation))
    swaps += [("`Explore`", target.explore), ("`AskUserQuestion`", ASK_USER_TEXT)]
    if target is CODEX:
        swaps += [
            (f"({label})", f"({codex_label_model(tier)})") for tier, label in MODEL_LABELS.items()
        ]
    return swaps


def read_generated_frontmatter(text: str) -> tuple[dict, str] | None:
    """Parse a generated frontmatter block (JSON strings, JSON lists, true/false) and the body below it."""
    end = text.find("\n---\n", 3)
    if not text.startswith("---\n") or end == -1:
        return None
    data: dict = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(": ")
        if not sep:
            return None
        try:
            data[key] = (
                json.loads(value)
                if value[:1] in '"['
                else {"true": True, "false": False}.get(value, value)
            )
        except json.JSONDecodeError:
            return None
    return data, text[end + 5 :].removeprefix("\n")


class Check:
    """Collects the problems found in one generated file, each reported as `<file>: <problem>`."""

    def __init__(self, errors: list[str], rel: str) -> None:
        self.errors = errors
        self.rel = rel

    def ok(self, condition: bool, problem: str) -> None:
        if not condition:
            self.errors.append(f"{self.rel}: {problem}")

    def eq(self, what: str, got: object, want: object) -> None:
        self.ok(got == want, f"{what} is {got!r}, expected {want!r}")


class Verifier:
    """Checks the files on disk against the Claude sources, field by field."""

    def __init__(self, src: Sources) -> None:
        self.src = src
        self.agents = set(src.agents)
        self.errors: list[str] = []

    def read(self, rel: str) -> str | None:
        """File text, or None after reporting it missing."""
        path = ROOT / rel
        if not path.is_file():
            self.errors.append(f"{rel}: missing; run python3 scripts/port.py")
            return None
        return path.read_text(encoding="utf-8")

    def frontmatter(self, rel: str, target: Target) -> tuple[Check, dict, str, str] | None:
        """(check, frontmatter fields, body, whole text) of a generated Markdown file, or None."""
        text = self.read(rel)
        if text is None:
            return None
        check = Check(self.errors, rel)
        parsed = read_generated_frontmatter(text)
        check.ok(parsed is not None, "frontmatter unreadable")
        if parsed is None:
            return None
        stale = stale_token(text, target)
        check.ok(stale is None, f"still contains the Claude-only token '{stale}'")
        return check, parsed[0], parsed[1], text

    def want(self, text: str, target: Target, **kind: Unpack[FileKind]) -> str:
        """`expected_text` with this run's agent names."""
        return expected_text(text, target, self.agents, **kind)

    def common(self, check: Check, doc: Doc, target: Target, instructions: str) -> None:
        """Body first, every preloaded skill in order, the turn-limit rule iff `maxTurns` is set."""
        fm = doc.fm
        check.ok(
            instructions.startswith(
                self.want(doc.body, target, agent=True, rewrites=f"agents/{doc.name}.md")
            ),
            "instructions do not start with the transformed Claude body",
        )
        pos = 0
        for skill in as_list(fm.get("skills")):
            chunk = f"## Preloaded skill: {skill}\n\n"
            chunk += BASE_DIR_LINE.format(root=target.root, skill=skill) + "\n\n"
            chunk += self.want(self.src.skills[skill].body, target, skill=skill)
            found = instructions.find(chunk, pos)
            check.ok(found != -1, f"preloaded skill '{skill}' is missing or out of order")
            pos = max(pos, found + len(chunk))
        limit = "Stop and report what you have after "
        turns = f"{limit}{int(fm['maxTurns'])} turns." if fm.get("maxTurns") else None
        check.ok(
            (turns in instructions) if turns else (limit not in instructions),
            f"turn limit rule {'missing' if turns else 'present without maxTurns'}",
        )

    def copilot_agent(self, doc: Doc) -> None:
        fm = doc.fm
        rel = f"{COPILOT.dir}/com.github.copilot/agents/{doc.name}.agent.md"
        loaded = self.frontmatter(rel, COPILOT)
        if loaded is None:
            return
        check, got, body, _ = loaded
        check.eq(
            "frontmatter keys",
            sorted(got),
            [
                "description",
                "include-custom-instructions",
                "model",
                "name",
                "reasoningEffort",
                "tools",
            ],
        )
        check.eq("name", got.get("name"), doc.name)
        check.eq("description", got.get("description"), self.want(fm["description"], COPILOT))
        check.eq("model", got.get("model"), MODEL_MAP["copilot"][fm["model"]])
        check.eq("reasoningEffort", got.get("reasoningEffort"), fm["effort"])
        omit = is_true(fm.get("omitClaudeMd"))
        check.eq(
            "include-custom-instructions",
            got.get("include-custom-instructions"),
            not omit,
        )
        listed_tools = got.get("tools")
        tools = listed_tools if isinstance(listed_tools, list) else []
        check.eq(
            "tools",
            sorted(tools),
            sorted({alias for t in agent_tools(fm) if (alias := TOOL_MAP[t])}),
        )
        check.eq("tools listed twice", len(tools), len(set(tools)))
        check.ok(
            "## Tools" not in body and "## Read-only" not in body,
            "has Codex-only sections",
        )
        self.common(check, doc, COPILOT, body)

    def codex_agent(self, doc: Doc, role_dir: str = f"{CODEX.dir}/agents") -> None:
        fm = doc.fm
        rel = f"{role_dir}/{doc.name}.toml"
        text = self.read(rel)
        if text is None:
            return
        check = Check(self.errors, rel)
        try:
            got = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            check.ok(False, f"not valid TOML ({exc})")
            return
        stale = stale_token(text, CODEX)
        check.ok(stale is None, f"still contains the Claude-only token '{stale}'")
        check.eq("keys outside the allowed set", sorted(set(got) - CODEX_ROLE_KEYS), [])
        check.eq("name", got.get("name"), doc.name)
        check.eq(
            "description",
            got.get("description"),
            self.want(fm["description"], CODEX, rewrites=f"agents/{doc.name}.md:description"),
        )
        want_model, want_effort = CODEX_PAIRS[fm["model"], fm["effort"]]
        check.eq("model", got.get("model"), want_model)
        check.eq("model_reasoning_effort", got.get("model_reasoning_effort"), want_effort)
        no_shell = {"shell_tool": False}
        check.eq(
            "[features]",
            got.get("features"),
            None if needs_codex_shell(fm) else no_shell,
        )
        instructions = got.get("developer_instructions")
        check.ok(isinstance(instructions, str), "developer_instructions is not a string")
        if not isinstance(instructions, str):
            return
        self.common(check, doc, CODEX, instructions)
        tools = codex_capabilities(fm)
        check.ok(
            f"## Tools\n\nUse only these tools: {tools}." in instructions,
            "tools rule missing or different",
        )
        read_only = bool(WRITE_TOOLS & set(as_list(fm.get("disallowedTools"))))
        check.ok(
            (READ_ONLY_RULE in instructions) == read_only,
            "read-only rule is "
            + ("missing" if read_only else "present without Edit/Write disallowed"),
        )

    def skill(self, doc: Doc, target: Target) -> None:
        for path in source_files(doc.path.parent):
            inside = path.relative_to(doc.path.parent).as_posix()
            rel = f"{target.dir}/skills/{doc.name}/{inside}"
            text = self.read(rel)
            if text is None:
                continue
            check = Check(self.errors, rel)
            if inside != "SKILL.md":
                check.ok(
                    (ROOT / rel).read_bytes() == skill_file_bytes(path),
                    "differs from the Claude source",
                )
                continue
            check.ok(
                text == self.want(doc.text, target, skill=doc.name),
                "is not the transformed Claude SKILL.md",
            )
            stale = stale_token(text, target)
            check.ok(stale is None, f"still contains the Claude-only token '{stale}'")

    def command(self, doc: Doc, target: Target) -> None:
        fm, name = doc.fm, doc.name
        rel = f"{target.dir}/skills/{name}/SKILL.md"
        loaded = self.frontmatter(rel, target)
        if loaded is None:
            return
        check, got, body, text = loaded
        check.eq("name", got.get("name"), name)
        check.eq(
            "description",
            got.get("description"),
            self.want(fm["description"], target, rewrites=f"commands/{name}.md:description"),
        )
        check.ok("$ARGUMENTS" not in text, "still contains $ARGUMENTS")
        check.ok(
            self.want(doc.body, target, command=True, rewrites=f"commands/{doc.name}.md") in body,
            "does not contain the transformed command body",
        )
        if target is COPILOT:
            keys = ["argument-hint", "description", "disable-model-invocation", "name"]
            check.eq("frontmatter keys", sorted(got), keys)
            check.eq("argument-hint", got.get("argument-hint"), fm["argument-hint"])
            check.eq("disable-model-invocation", got.get("disable-model-invocation"), True)
            return
        check.eq("frontmatter keys", sorted(got), ["description", "name"])
        check.eq(
            "first body line",
            body.split("\n\n", 1)[0],
            f"Arguments hint: {fm['argument-hint']}",
        )
        yaml_rel = f"{target.dir}/skills/{name}/agents/openai.yaml"
        yaml = self.read(yaml_rel)
        if yaml is not None:
            Check(self.errors, yaml_rel).eq("content", yaml, OPENAI_YAML)

    def json_file(self, rel: str) -> dict | None:
        text = self.read(rel)
        if text is None:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            self.errors.append(f"{rel}: not valid JSON ({exc})")
            return None
        return data if isinstance(data, dict) else None

    def manifests(self) -> None:
        """Both plugin manifests carry the Claude plugin's name, description and (Copilot) version, author, repository."""
        plugin = self.src.plugin
        copilot_rel, codex_rel = (
            f"{COPILOT.dir}/plugin.json",
            f"{CODEX.dir}/.codex-plugin/plugin.json",
        )
        if (got := self.json_file(copilot_rel)) is not None:
            check = Check(self.errors, copilot_rel)
            check.eq(
                "keys",
                list(got),
                ["$schema", "name", "version", "description", "author", "repository"],
            )
            for key in ("name", "version", "description", "author", "repository"):
                check.eq(key, got.get(key), plugin.get(key))
        if (got := self.json_file(codex_rel)) is not None:
            check = Check(self.errors, codex_rel)
            check.eq(
                "keys (no version, no commands)",
                list(got),
                ["name", "description", "skills"],
            )
            check.eq("skills", got.get("skills"), "./skills")
            check.eq("description", got.get("description"), plugin.get("description"))

    def catalog(self, target: Target) -> None:
        """The catalog lists exactly the target's plugins; each source folder exists and is the expected one."""
        got = self.json_file(target.catalog)
        if got is None:
            return
        check = Check(self.errors, target.catalog)
        plugins = got.get("plugins")
        listed = plugins if isinstance(plugins, list) else []
        check.eq("name", got.get("name"), self.src.marketplace.get("name"))
        expected = catalog_plugins(target)
        check.eq("listed plugins", [p.get("name") for p in listed], [name for name, _ in expected])
        for entry, (_, folder) in zip(listed, expected, strict=False):
            source = entry.get("source")
            path = str(source.get("path") if isinstance(source, dict) else source)
            check.ok((ROOT / path).is_dir(), f"source {path!r} is not a folder")
            check.eq("source", path.removeprefix("./"), folder)

    def policy(self, target: Target) -> None:
        text = self.read(target.policy)
        if text is None:
            return
        check = Check(self.errors, target.policy)
        check.eq("first line", text.split("\n", 1)[0], POLICY_BANNER)
        left = [n for n in sorted(self.agents) if re.search(rf"agent-skills:{n}(?![\w-])", text)]
        check.eq("agent-skills:<agent> references left", left, [])
        check.ok("`Explore`" not in text, "still names `Explore`")
        check.ok(
            (target.explore in text) == ("`Explore`" in self.src.policy),
            f"built-in explorer name {target.explore} is missing or unexpected",
        )

    def routing(self, target: Target) -> None:
        text = self.read(target.routing)
        if text is None:
            return
        check = Check(self.errors, target.routing)
        check.eq("first line", text.split("\n", 1)[0], ROUTING_BANNER)
        left = [n for n in sorted(self.agents) if re.search(rf"agent-skills:{n}(?![\w-])", text)]
        check.eq("agent-skills:<agent> references left", left, [])
        check.ok(stale_token(text, target) is None, "still has a Claude-only token")

    def forbidden_files(self) -> None:
        """Claude Code loads CLAUDE.md and AGENTS.md; Copilot reads a root marketplace.json first."""
        for path in sorted((ROOT / PORTS).rglob("*")):
            if path.name in {"CLAUDE.md", "AGENTS.md"}:
                rel = path.relative_to(ROOT).as_posix()
                self.errors.append(f"{rel}: Claude Code would load this file; delete it")
        if (ROOT / "marketplace.json").exists():
            self.errors.append(
                "marketplace.json: Copilot would read it before its own catalog; delete it"
            )

    def source_plugin_agents(self) -> None:
        """The Codex roles generated from the agents of the `SOURCE_PLUGINS` plugins."""
        for plugin, agents in self.src.source_agents.items():
            for doc in agents.values():
                self.codex_agent(doc, f"{SOURCE_PLUGINS['codex'][plugin]}/{ROLES_DIR}")

    def run(self) -> list[str]:
        for doc in self.src.agents.values():
            self.copilot_agent(doc)
            self.codex_agent(doc)
        self.source_plugin_agents()
        for target in TARGETS:
            for doc in self.src.skills.values():
                self.skill(doc, target)
            for doc in self.src.commands.values():
                self.command(doc, target)
            self.catalog(target)
            self.policy(target)
            self.routing(target)
        self.manifests()
        self.forbidden_files()
        return self.errors


def check(src: Sources, files: dict[str, Blob]) -> list[str]:
    """Drift (regenerate into a temp dir, compare byte for byte) plus field-level equivalence."""
    with tempfile.TemporaryDirectory() as tmp:
        sync(files, Path(tmp))
        errors = drift(Path(tmp))
    errors += Verifier(src).run()
    return list(dict.fromkeys(errors))


# --- report -----------------------------------------------------------------------------------


def report(src: Sources) -> str:
    """A Markdown table: per artifact type, what each port does and what is not mapped."""
    n_agents, n_skills, n_commands = len(src.agents), len(src.skills), len(src.commands)
    preload = sum(1 for d in src.agents.values() if d.fm.get("skills"))
    turns = sum(1 for d in src.agents.values() if d.fm.get("maxTurns"))
    omit = sum(1 for d in src.agents.values() if is_true(d.fm.get("omitClaudeMd")))
    no_bash = ", ".join(n for n, d in src.agents.items() if not needs_codex_shell(d.fm))
    rows = [
        (
            f"Skills ({n_skills})",
            "Folder copied. In SKILL.md: `${CLAUDE_SKILL_DIR}`, `${CLAUDE_PLUGIN_ROOT}`, `~/.claude/plugins` become the install paths; `agent-skills:<agent>` becomes `<agent>`, `/agent-skills:<name>` becomes `/<name>`; `Explore` and `AskUserQuestion` get the tool's own wording",
            "Same, but `/agent-skills:<name>` stays and `(Haiku)`, `(Sonnet)`, `(Opus)` become the GPT tier",
            "`references/` and `scripts/` are copied byte-identical, so their Claude path mentions stay",
        ),
        (
            f"Commands ({n_commands})",
            "`skills/<name>/SKILL.md` with `disable-model-invocation: true`; `$ARGUMENTS` becomes a sentence",
            "`skills/<name>/SKILL.md` plus `agents/openai.yaml` (implicit invocation off); `Arguments hint:` line; `$ARGUMENTS` becomes a sentence",
            "No argument substitution in either tool; no command files (Codex skips `$ARGUMENTS`); `Explore` becomes the tool's built-in explorer; the Claude-only line on Explore's Haiku override is dropped",
        ),
        (
            f"Agents ({n_agents}): identity",
            "`com.github.copilot/agents/<name>.agent.md`; model to the same Claude id; `effort` to `reasoningEffort`; delegation rules point to copilot-instructions.md and AGENTS.md",
            "`agents/<name>.toml`; `model` and `effort` together to a GPT model and `model_reasoning_effort` (table in docs/ports.md); delegation rules point to AGENTS.md",
            "Codex plugins cannot carry agents: copy `agents/*.toml` to `~/.codex/agents/`",
        ),
        (
            "Agents: tools",
            "`tools` = mapped aliases (`Skill` and the optional `mcp__fff__` tools dropped, `disallowedTools` removed); enforced",
            f"`## Tools` (what each tool allows, not Claude tool names) and `## Read-only` (project files unchanged, temp files allowed) rules in the text; `shell_tool = false` only without Bash, Read, Grep and Glob ({no_bash}), because Codex reads files through its shell",
            "Codex: no per-role tool allowlist; limits are rules, not enforcement",
        ),
        (
            f"Agents: `skills:` ({preload})",
            "Skill body appended as `## Preloaded skill: <name>`, after a line giving the skill's base directory",
            "Same",
            "Neither tool preloads skills",
        ),
        (
            f"Agents: `maxTurns` ({turns})",
            "Stated as a rule in the text",
            "Same",
            "Not enforced by either tool",
        ),
        (
            f"Agents: `omitClaudeMd` ({omit})",
            "`include-custom-instructions: false`",
            "-",
            "Codex: no knob for it",
        ),
        (
            "Offload policy",
            "`user-config/offload-policy.copilot.md`: bare agent names, `Explore` becomes `explore` (built-in agent)",
            "`user-config/offload-policy.codex.md`: bare agent names, `Explore` becomes `explorer` (built-in role)",
            "The built-in explorers keep their own model (the Haiku override is Claude-only)",
        ),
        (
            "Routing table, recommended prompt",
            "`user-config/routing.copilot.md` and the README block between the `recommended-prompt` markers: same naming as the policy, `/agent-skills:<name>` becomes `/<name>`",
            "`user-config/routing.codex.md` and the README block: same naming as the policy",
            "Superpowers skill names are the same in every tool",
        ),
        (
            "Manifest, catalog",
            "`plugin.json` (with version); `.github/plugin/marketplace.json`",
            "`.codex-plugin/plugin.json` (no version, no commands); `.agents/plugins/marketplace.json`",
            "Only agent-skills is listed",
        ),
        ("Mods, evals", "-", "-", "Not ported (Claude-only)"),
    ]
    lines = ["| Artifact | Copilot CLI | Codex | Not mapped |", "|---|---|---|---|"]
    lines += [f"| {' | '.join(row)} |" for row in rows]
    return "\n".join(lines)


# --- command line -----------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    """The command line: write by default, or `--check`, or `--report`."""
    parser = argparse.ArgumentParser(description="Generate and verify the Copilot and Codex ports.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify that the ports are current and equivalent",
    )
    mode.add_argument(
        "--report",
        action="store_true",
        help="print what maps to what and what does not",
    )
    return parser


def _fail(errors: list[str]) -> int:
    """Print every error, one per line, and return the failing exit code."""
    for error in errors:
        print(error)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    src, errors = load_sources()
    files: dict[str, Blob] = {}
    if not errors:
        files, errors = generate(src)
    if errors:
        return _fail(errors)
    if args.report:
        print(report(src))
        return 0
    if args.check:
        errors = check(src, files)
        if errors:
            return _fail(errors)
        print(
            f"OK: {len(src.agents)} agents, {len(src.skills)} skills, {len(src.commands)} commands "
            f"ported to copilot and codex ({len(files)} files current and equivalent)"
        )
        return 0
    written, removed = sync(files, ROOT)
    print(f"Wrote {written} of {len(files)} files, removed {removed} stale")
    return 0


if __name__ == "__main__":
    sys.exit(main())
