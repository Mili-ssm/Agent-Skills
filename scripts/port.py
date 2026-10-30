#!/usr/bin/env python3
"""Generate the GitHub Copilot CLI and OpenAI Codex ports of the agent-skills plugin (ADR 0015, docs/ports.md).

  python3 scripts/port.py            write ports/, both catalogs and both policy variants
  python3 scripts/port.py --check    prove the copies are current and equivalent to the Claude sources
  python3 scripts/port.py --report   print what each artifact type maps to and what does not map

The Claude sources (plugins/, .claude-plugin/, user-config/offload-policy.md) are only read, so Claude Code
behaves exactly as before. No CLAUDE.md or AGENTS.md is generated (Claude Code would load it).

Standard library only (Python 3.11+, tomllib). Exit code 0 = ok, 1 = errors (printed one per line).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import tomllib
from validate import FrontmatterError, as_list, is_true, parse_frontmatter

# Repo root = parent of scripts/, independent of the current working directory.
ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "agent-skills"
CLAUDE_MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
POLICY = ROOT / "user-config" / "offload-policy.md"
PORTS = "ports"

# Catalog name shared with .claude-plugin/marketplace.json; it is part of every install path (checked on load).
MARKETPLACE = "mili-ssm"
# The one plugin that is ported; the mods are Claude-only (no mods API elsewhere).
PLUGIN_NAME = "agent-skills"

MODEL_MAP = {
    # Copilot runs the same Claude models, so the mapping is exact.
    "copilot": {
        "haiku": "claude-haiku-5.5",
        "sonnet": "claude-sonnet-5.5",
        "opus": "claude-opus-5.5",
    },
    # Nearest tier in Codex models.json (2026-10): luna fast and affordable, sol default workhorse, astra frontier.
    "codex": {
        "haiku": "gpt-6-luna",
        "sonnet": "gpt-6.1-sol",
        "opus": "gpt-6-astra",
    },
}
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
# Both tools take the same effort names as Claude, so the value is copied.
EFFORTS = {"low", "medium", "high"}
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
TOOL_CAPABILITY = {
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
}
# Command lines that state Claude-only facts; the ports drop them instead of carrying a false claim.
CLAUDE_ONLY_LINE = re.compile(
    r"^- `Explore` runs on Haiku only with the user-scope override.*(?:\n|\Z)",
    re.MULTILINE,
)
# Codex's equivalent of Claude's disable-model-invocation: the skill runs only when the user names it.
OPENAI_YAML = "policy:\n  allow_implicit_invocation: false\n"
AGENT_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
POLICY_BANNER = (
    "<!-- Generated by scripts/port.py from offload-policy.md; edit that file. -->"
)
READ_ONLY_RULE = (
    "## Read-only\n\nLeave the project's files unchanged: do not use apply_patch or any "
    "edit tool, and run only commands that do not change them (temp dirs and build "
    "caches are fine). Claude Code enforces this; Codex does not, so it is your rule."
)
CATALOG_DESCRIPTION = (
    "agent-skills for {label}: specialist skills and agents generated from the "
    "Claude Code plugin (scripts/port.py)."
)


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
)
TARGETS = (COPILOT, CODEX)


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
    skills: dict[str, Doc]
    agents: dict[str, Doc]
    commands: dict[str, Doc]


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
    pattern: str, allowed: set[str], required: tuple[str, ...], errors: list[str]
) -> dict[str, Doc]:
    """Read every Markdown source matching `pattern`; unknown or missing frontmatter fields are errors."""
    docs: dict[str, Doc] = {}
    for path in sorted(PLUGIN.glob(pattern)):
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


def check_agent(doc: Doc, skills: dict[str, Doc], errors: list[str]) -> None:
    """Report agent values the tool mappings do not cover, instead of porting a guess."""
    fm, rel = doc.fm, doc.path.relative_to(ROOT)
    if fm.get("model") not in MODEL_MAP["copilot"]:
        errors.append(f"{rel}: model {fm.get('model')!r} is not in MODEL_MAP")
    if fm.get("effort") not in EFFORTS:
        errors.append(
            f"{rel}: effort {fm.get('effort')!r} is not one of {sorted(EFFORTS)}"
        )
    for tool in as_list(fm.get("tools")):
        if tool not in TOOL_MAP or tool not in TOOL_CAPABILITY:
            errors.append(
                f"{rel}: tool '{tool}' is not in TOOL_MAP and TOOL_CAPABILITY"
            )
    for skill in as_list(fm.get("skills")):
        if skill not in skills:
            errors.append(f"{rel}: preloads unknown skill '{skill}'")
    turns = str(fm.get("maxTurns", "1"))
    if not (turns.isdigit() and int(turns) > 0):
        errors.append(f"{rel}: maxTurns must be a positive integer")
    if fm.get("omitClaudeMd") not in (None, "true", "false"):
        errors.append(f"{rel}: omitClaudeMd must be true or false")
    if not copilot_tools(fm):
        errors.append(f"{rel}: no tool maps to a Copilot tool")
    # Edit and Write share one Copilot alias: a blocked tool whose alias another tool keeps cannot be enforced.
    kept = set(copilot_tools(fm))
    for tool in as_list(fm.get("disallowedTools")):
        if TOOL_MAP.get(tool) in kept:
            errors.append(
                f"{rel}: '{tool}' is disallowed but Copilot alias '{TOOL_MAP[tool]}' stays granted"
            )


def load_sources() -> tuple[Sources, list[str]]:
    """Read the plugin, marketplace, policy, skills, agents and commands, with every problem found."""
    errors: list[str] = []
    plugin = json.loads(
        (PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    marketplace = json.loads(CLAUDE_MARKETPLACE.read_text(encoding="utf-8"))
    if marketplace.get("name") != MARKETPLACE:
        errors.append(
            f".claude-plugin/marketplace.json: name is {marketplace.get('name')!r}; MARKETPLACE says {MARKETPLACE!r}"
        )
    if plugin.get("name") != PLUGIN_NAME:
        errors.append(
            f"plugin.json: name is {plugin.get('name')!r}; PLUGIN_NAME says {PLUGIN_NAME!r}"
        )
    for key in ("description", "author", "repository"):
        if not plugin.get(key):
            errors.append(
                f"plugins/{PLUGIN_NAME}/.claude-plugin/plugin.json: missing '{key}'"
            )
    if not (marketplace.get("owner") or {}).get("name"):
        errors.append(".claude-plugin/marketplace.json: missing owner.name")
    skills = load_docs(
        "skills/*/SKILL.md", SKILL_FIELDS, ("name", "description"), errors
    )
    agents = load_docs(
        "agents/*.md",
        AGENT_FIELDS,
        ("name", "description", "tools", "model", "effort"),
        errors,
    )
    commands = load_docs(
        "commands/*.md", COMMAND_FIELDS, ("description", "argument-hint"), errors
    )
    for doc in agents.values():
        check_agent(doc, skills, errors)
    for name, doc in commands.items():
        if name in skills:
            errors.append(
                f"{doc.path.relative_to(ROOT)}: command '{name}' collides with the skill of the same name"
            )
        if not is_true(doc.fm.get("disable-model-invocation")):
            errors.append(
                f"{doc.path.relative_to(ROOT)}: commands must set disable-model-invocation: true"
            )
    return Sources(
        plugin,
        marketplace,
        POLICY.read_text(encoding="utf-8"),
        skills,
        agents,
        commands,
    ), errors


# --- text transforms --------------------------------------------------------------------------


def rename_agents(text: str, agents: set[str]) -> str:
    """Transform 2: `agent-skills:<agent>` -> `<agent>`; skills and commands keep their namespace."""
    return PLUGIN_REF.sub(
        lambda m: m.group(1) if m.group(1) in agents else m.group(0), text
    )


def transform(
    text: str,
    target: Target,
    agents: set[str],
    *,
    skill: str | None = None,
    command: bool = False,
    agent: bool = False,
) -> str:
    """All text transforms for one tool; `command` and `agent` add the ones only those files need."""
    if SKILL_DIR_VAR in text:
        if skill is None:
            raise PortError(
                f"{SKILL_DIR_VAR} outside a skill has no folder to point to"
            )
        text = text.replace(SKILL_DIR_VAR, f"{target.root}/skills/{skill}")
    text = text.replace(PLUGIN_ROOT_VAR, target.root).replace(
        CLAUDE_PLUGINS, target.base
    )
    if target is COPILOT:  # Copilot invokes plugin skills by their bare name
        text = text.replace("/agent-skills:", "/")
    text = rename_agents(text, agents)
    if command:
        text = CLAUDE_ONLY_LINE.sub("", text).replace("$ARGUMENTS", ARGUMENTS_TEXT)
    if agent:
        text = text.replace(DELEGATION_RULE, target.delegation)
    text = text.replace("`Explore`", target.explore)
    text = text.replace("`AskUserQuestion`", ASK_USER_TEXT)
    if target is CODEX:
        for tier, label in MODEL_LABELS.items():
            text = text.replace(f"({label})", f"({MODEL_MAP[target.key][tier]})")
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


def is_executable(path: Path) -> bool:
    """Whether any execute bit is set."""
    return bool(path.stat().st_mode & 0o111)


def stale_token(text: str, target: Target) -> str | None:
    """The first token left in an instruction file that is Claude-only for `target`, if any."""
    own = (
        ["/agent-skills:"]
        if target is COPILOT
        else [f"({m})" for m in MODEL_LABELS.values()]
    )
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
        skill: str | None = None,
        command: bool = False,
        agent: bool = False,
    ) -> str:
        """`transform` that records a failure against `where` instead of raising."""
        try:
            return transform(
                text, target, self.agents, skill=skill, command=command, agent=agent
            )
        except PortError as exc:
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
                "description": plugin["description"],
                "author": plugin["author"],
                "repository": plugin["repository"],
            }
            self.put(f"{target.dir}/plugin.json", dumps_json(data))
        else:
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
                    text = self.t(
                        doc.text, target, f"skills/{name}/SKILL.md", skill=name
                    )
                    self.put_instruction(dest, text, target)
                else:
                    self.put(dest, path.read_bytes(), executable=is_executable(path))

    def commands(self, target: Target) -> None:
        """Commands become user-only skills: neither tool runs Claude command files."""
        for name, doc in self.src.commands.items():
            where = f"commands/{name}.md"
            body = self.t(doc.body, target, where, command=True)
            description = q(self.t(doc.fm["description"], target, where))
            dest = f"{target.dir}/skills/{name}"
            if target is COPILOT:
                pairs = [
                    ("name", q(name)),
                    ("description", description),
                    ("argument-hint", q(doc.fm["argument-hint"])),
                    ("disable-model-invocation", "true"),
                ]
                self.put_instruction(
                    f"{dest}/SKILL.md", f"{frontmatter(pairs)}\n{body}\n", target
                )
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
            tools = ", ".join(TOOL_CAPABILITY[t] for t in agent_tools(fm))
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
        """One agent file per Claude agent: a Copilot .agent.md or a Codex role .toml."""
        for name, doc in self.src.agents.items():
            fm = doc.fm
            description = self.t(fm["description"], target, f"agents/{name}.md")
            instructions = self.instructions(doc, target)
            model = q(MODEL_MAP[target.key][fm["model"]])
            if target is COPILOT:
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
                dest = f"{target.dir}/com.github.copilot/agents/{name}.agent.md"
                self.put_instruction(
                    dest, f"{frontmatter(pairs)}\n{instructions}", target
                )
            else:
                lines = [
                    f"name = {q(name)}",
                    f"description = {q(description)}",
                    f"developer_instructions = {toml_multiline(instructions)}",
                    f"model = {model}",
                    f"model_reasoning_effort = {q(fm['effort'])}",
                ]
                if not needs_codex_shell(fm):
                    lines += ["", "[features]", "shell_tool = false"]
                self.put_instruction(
                    f"{target.dir}/agents/{name}.toml", "\n".join(lines) + "\n", target
                )

    def catalogs(self) -> None:
        """One marketplace file per tool, listing only agent-skills."""
        plugin = self.src.plugin
        owner = self.src.marketplace["owner"]["name"]
        copilot = {
            "name": MARKETPLACE,
            "owner": {"name": owner},
            "metadata": {
                "description": CATALOG_DESCRIPTION.format(label=COPILOT.label)
            },
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
                {
                    "name": PLUGIN_NAME,
                    "source": {"source": "local", "path": f"./{CODEX.dir}"},
                }
            ],
        }
        self.put(COPILOT.catalog, dumps_json(copilot))
        self.put(CODEX.catalog, dumps_json(codex))

    def policies(self) -> None:
        """The offload policy with bare agent names and the tool's own name for the built-in explorer."""
        for target in TARGETS:
            text = self.t(self.src.policy, target, "user-config/offload-policy.md")
            self.put(target.policy, f"{POLICY_BANNER}\n\n{text.rstrip(chr(10))}\n")


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
    return gen.files, list(dict.fromkeys(gen.errors))


# --- writing and drift ------------------------------------------------------------------------


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
    removed = 0
    ports = base / PORTS
    for path in sorted(ports.rglob("*"), reverse=True) if ports.is_dir() else []:
        if path.is_file() and path.relative_to(base).as_posix() not in files:
            path.unlink()
            removed += 1
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
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
            errors.append(
                f"{rel}: differs from the generated version; run python3 scripts/port.py"
            )
        elif is_executable(disk) != is_executable(path):
            errors.append(f"{rel}: executable bit differs; run python3 scripts/port.py")
    errors.extend(
        f"{p.relative_to(ROOT).as_posix()}: extra file, not generated; run python3 scripts/port.py"
        for p in sorted((ROOT / PORTS).rglob("*"))
        if p.is_file() and p.relative_to(ROOT).as_posix() not in wanted
    )
    return errors


# --- equivalence: parse the files on disk back and compare them with the Claude sources ---------


def expected_text(
    text: str,
    target: Target,
    agents: set[str],
    *,
    skill: str | None = None,
    command: bool = False,
    agent: bool = False,
) -> str:
    """What `text` must become for `target`, as an ordered list of swaps (independent of the generator)."""
    swaps = [
        (SKILL_DIR_VAR, f"{target.root}/skills/{skill}"),
        (PLUGIN_ROOT_VAR, target.root),
        (CLAUDE_PLUGINS, target.base),
    ]
    if target is COPILOT:
        swaps.append(("/agent-skills:", "/"))
    for old, new in swaps:
        text = text.replace(old, new)
    pieces = re.split(r"((?<![\w-])agent-skills:[a-z0-9-]+(?!\w))", text)
    for i in range(1, len(pieces), 2):
        name = pieces[i].removeprefix("agent-skills:")
        pieces[i] = name if name in agents else pieces[i]
    text = "".join(pieces)
    swaps = []
    if command:
        text = CLAUDE_ONLY_LINE.sub("", text)
        swaps.append(("$ARGUMENTS", ARGUMENTS_TEXT))
    if agent:
        swaps.append((DELEGATION_RULE, target.delegation))
    swaps += [("`Explore`", target.explore), ("`AskUserQuestion`", ASK_USER_TEXT)]
    if target is CODEX:
        swaps += [
            (f"({label})", f"({MODEL_MAP['codex'][tier]})")
            for tier, label in MODEL_LABELS.items()
        ]
    for old, new in swaps:
        text = text.replace(old, new)
    return text


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

    def frontmatter(
        self, rel: str, target: Target
    ) -> tuple[Check, dict, str, str] | None:
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

    def want(
        self,
        text: str,
        target: Target,
        skill: str | None = None,
        command: bool = False,
        agent: bool = False,
    ) -> str:
        """`expected_text` with this run's agent names."""
        return expected_text(
            text, target, self.agents, skill=skill, command=command, agent=agent
        )

    def common(self, check: Check, doc: Doc, target: Target, instructions: str) -> None:
        """Body first, every preloaded skill in order, the turn-limit rule iff `maxTurns` is set."""
        fm = doc.fm
        check.ok(
            instructions.startswith(self.want(doc.body, target, agent=True)),
            "instructions do not start with the transformed Claude body",
        )
        pos = 0
        for skill in as_list(fm.get("skills")):
            chunk = f"## Preloaded skill: {skill}\n\n"
            chunk += BASE_DIR_LINE.format(root=target.root, skill=skill) + "\n\n"
            chunk += self.want(self.src.skills[skill].body, target, skill=skill)
            found = instructions.find(chunk, pos)
            check.ok(
                found != -1, f"preloaded skill '{skill}' is missing or out of order"
            )
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
            ["description", "include-custom-instructions", "model", "name"]
            + ["reasoningEffort", "tools"],
        )
        check.eq("name", got.get("name"), doc.name)
        check.eq(
            "description", got.get("description"), self.want(fm["description"], COPILOT)
        )
        check.eq("model", got.get("model"), MODEL_MAP["copilot"][fm["model"]])
        check.eq("reasoningEffort", got.get("reasoningEffort"), fm["effort"])
        omit = is_true(fm.get("omitClaudeMd"))
        check.eq(
            "include-custom-instructions",
            got.get("include-custom-instructions"),
            not omit,
        )
        tools = got.get("tools") if isinstance(got.get("tools"), list) else []
        check.eq(
            "tools",
            sorted(tools),
            sorted({TOOL_MAP[t] for t in agent_tools(fm)} - {None}),
        )
        check.eq("tools listed twice", len(tools), len(set(tools)))
        check.ok(
            "## Tools" not in body and "## Read-only" not in body,
            "has Codex-only sections",
        )
        self.common(check, doc, COPILOT, body)

    def codex_agent(self, doc: Doc) -> None:
        fm = doc.fm
        rel = f"{CODEX.dir}/agents/{doc.name}.toml"
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
            "description", got.get("description"), self.want(fm["description"], CODEX)
        )
        check.eq("model", got.get("model"), MODEL_MAP["codex"][fm["model"]])
        check.eq(
            "model_reasoning_effort", got.get("model_reasoning_effort"), fm["effort"]
        )
        no_shell = {"shell_tool": False}
        check.eq(
            "[features]",
            got.get("features"),
            None if needs_codex_shell(fm) else no_shell,
        )
        instructions = got.get("developer_instructions")
        check.ok(
            isinstance(instructions, str), "developer_instructions is not a string"
        )
        if not isinstance(instructions, str):
            return
        self.common(check, doc, CODEX, instructions)
        tools = ", ".join(TOOL_CAPABILITY[t] for t in agent_tools(fm))
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
                    (ROOT / rel).read_bytes() == path.read_bytes(),
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
            "description", got.get("description"), self.want(fm["description"], target)
        )
        check.ok("$ARGUMENTS" not in text, "still contains $ARGUMENTS")
        check.ok(
            self.want(doc.body, target, command=True) in body,
            "does not contain the transformed command body",
        )
        if target is COPILOT:
            keys = ["argument-hint", "description", "disable-model-invocation", "name"]
            check.eq("frontmatter keys", sorted(got), keys)
            check.eq("argument-hint", got.get("argument-hint"), fm["argument-hint"])
            check.eq(
                "disable-model-invocation", got.get("disable-model-invocation"), True
            )
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
        """Both plugin manifests carry the Claude plugin's name, description and (Copilot) author, repository."""
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
                ["$schema", "name", "description", "author", "repository"],
            )
            for key in ("name", "description", "author", "repository"):
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
        """The catalog lists only agent-skills, and its source folder exists and is the tool's plugin."""
        got = self.json_file(target.catalog)
        if got is None:
            return
        check = Check(self.errors, target.catalog)
        listed = got.get("plugins") if isinstance(got.get("plugins"), list) else []
        check.eq("name", got.get("name"), self.src.marketplace.get("name"))
        check.eq("listed plugins", [p.get("name") for p in listed], [PLUGIN_NAME])
        for entry in listed:
            source = entry.get("source")
            path = str(source.get("path") if isinstance(source, dict) else source)
            check.ok((ROOT / path).is_dir(), f"source {path!r} is not a folder")
            check.eq("source", path.removeprefix("./"), target.dir)

    def policy(self, target: Target) -> None:
        text = self.read(target.policy)
        if text is None:
            return
        check = Check(self.errors, target.policy)
        check.eq("first line", text.split("\n", 1)[0], POLICY_BANNER)
        left = [
            n
            for n in sorted(self.agents)
            if re.search(rf"agent-skills:{n}(?![\w-])", text)
        ]
        check.eq("agent-skills:<agent> references left", left, [])
        check.ok("`Explore`" not in text, "still names `Explore`")
        check.ok(
            (target.explore in text) == ("`Explore`" in self.src.policy),
            f"built-in explorer name {target.explore} is missing or unexpected",
        )

    def forbidden_files(self) -> None:
        """Claude Code loads CLAUDE.md and AGENTS.md; Copilot reads a root marketplace.json first."""
        for path in sorted((ROOT / PORTS).rglob("*")):
            if path.name in {"CLAUDE.md", "AGENTS.md"}:
                rel = path.relative_to(ROOT).as_posix()
                self.errors.append(
                    f"{rel}: Claude Code would load this file; delete it"
                )
        if (ROOT / "marketplace.json").exists():
            self.errors.append(
                "marketplace.json: Copilot would read it before its own catalog; delete it"
            )

    def run(self) -> list[str]:
        for doc in self.src.agents.values():
            self.copilot_agent(doc)
            self.codex_agent(doc)
        for target in TARGETS:
            for doc in self.src.skills.values():
                self.skill(doc, target)
            for doc in self.src.commands.values():
                self.command(doc, target)
            self.catalog(target)
            self.policy(target)
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
            "`agents/<name>.toml`; model to the nearest GPT tier; `effort` to `model_reasoning_effort`; delegation rules point to AGENTS.md",
            "Codex plugins cannot carry agents: copy `agents/*.toml` to `~/.codex/agents/`",
        ),
        (
            "Agents: tools",
            "`tools` = mapped aliases (`Skill` dropped, `disallowedTools` removed); enforced",
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
            "Manifest, catalog",
            "`plugin.json`; `.github/plugin/marketplace.json`",
            "`.codex-plugin/plugin.json` (no version, no commands); `.agents/plugins/marketplace.json`",
            "Only agent-skills is listed",
        ),
        ("Mods, evals", "-", "-", "Not ported (Claude-only)"),
    ]
    lines = ["| Artifact | Copilot CLI | Codex | Not mapped |", "|---|---|---|---|"]
    lines += [f"| {' | '.join(row)} |" for row in rows]
    return "\n".join(lines)


# --- command line -----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate and verify the Copilot and Codex ports."
    )
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
    args = parser.parse_args(argv)

    src, errors = load_sources()
    files: dict[str, Blob] = {}
    if not errors:
        files, errors = generate(src)
    if not errors and args.report:
        print(report(src))
        return 0
    if not errors and args.check:
        errors = check(src, files)
        if not errors:
            print(
                f"OK: {len(src.agents)} agents, {len(src.skills)} skills, {len(src.commands)} commands "
                f"ported to copilot and codex ({len(files)} files current and equivalent)"
            )
            return 0
    if not errors:
        written, removed = sync(files, ROOT)
        print(f"Wrote {written} of {len(files)} files, removed {removed} stale")
        return 0
    for error in errors:
        print(error)
    return 1


if __name__ == "__main__":
    sys.exit(main())
