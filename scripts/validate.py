#!/usr/bin/env python3
"""Validate skills, agents, commands and evals against the repo contract (docs/requirements.md, ADRs 0007, 0010).

Checks (each is a small function whose docstring names the requirement it enforces):
  - skills: `name` == folder (<= 64 chars, lowercase, digits, hyphens); `description` says what it does
    first, then its trigger ("Use when" / "Use to" / "Use before" / "Use after"), in third person, <= 1024
    chars; SKILL.md <= 150 lines; references/ is one level deep, files over 100 lines open with a
    `## Contents` heading, relative links resolve and a reference never links another reference.
  - agents: `name` == file, `tools`, `effort` and a valid `model`; <= 120 lines; "Read-only" agents block
    Edit/Write/NotebookEdit, grant neither and set `omitClaudeMd: true`; preloaded skills exist.
  - workers (the WORKERS set): set `maxTurns`, have an agent file and a row in commands/offload.md, and are the
    only agents allowed to say "Use proactively".
  - commands: user-only, with `argument-hint` and `$ARGUMENTS`, naming existing agents/skills; every
    non-worker agent has a command that names it.
  - evals: grader patterns name existing skills/agents; no-trigger graders name all of them; offload
    `*-with-policy` cases embed user-config/offload-policy.md verbatim.
  - readme: the `## Catalog` tables in README.md list exactly the plugin's agents (with model and preloads), skills
    and commands.
  - public paths: the files and README anchors installed users rely on exist (ADR 0026).
  - versions: each plugin has a SemVer `version` in plugin.json and a CHANGELOG entry for it; catalogs carry none (ADR 0027).
    `--release` adds git checks against the plugin's latest tag (a dev branch always differs from tags, so they are opt-in).
  - ports: `scripts/port.py --check` finds the Copilot and Codex copies under ports/ current and equivalent (ADR 0015).

Standard library only so it runs in any fresh environment: `python3 scripts/validate.py`.
Exit code 0 = valid, 1 = at least one error (errors are printed one per line).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from promptkit import fragments
from promptkit.models import CATALOG, load_catalog

# Repo root = parent of the scripts/ directory, independent of the current working directory.
ROOT = Path(__file__).resolve().parent.parent
# The agent-skills plugin lives in its own folder so the marketplace can list mods beside it (ADR 0011).
PLUGIN = ROOT / "plugins" / "agent-skills"
POLICY = ROOT / "user-config" / "offload-policy.md"
OFFLOAD_COMMAND = PLUGIN / "commands" / "offload.md"
SKILL_MAX_LINES = 150
AGENT_MAX_LINES = 120
# Cheap offload workers (ADR 0010): the only agents that may say "Use proactively"; each sets maxTurns and
# has a row in commands/offload.md. `Explore` is a user-scope agent (user-agents/), so it is not listed.
WORKERS = {
    "check-runner",
    "summarizer",
    "researcher",
    "implementer",
    "fixer",
    "ui-verifier",
    "skeptical-reviewer",
}
# Tools a "Read-only" agent must neither hold nor leave unblocked (N7).
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
# Accepted trigger openings for descriptions (N2).
TRIGGER = re.compile(r"\bUse (when|to|before|after|proactively)\b")
PROACTIVE = re.compile(r"\buse proactively\b", re.IGNORECASE)
# Skill/agent name format and description limits from Anthropic's skill-authoring guide.
NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
DESCRIPTION_MAX = 1024
QUOTED = re.compile(r'["“][^"“”.!?\n]{1,60}["”]')  # a short quoted user phrase
# Descriptions are injected into the system prompt, so first/second person breaks discovery.
# "I" is matched in capitals only and skips "I/O"; the other pronouns match in any case.
PERSON = re.compile(r"(?-i:\bI\b(?!/))|\b(?:we|you|your|our)\b", re.IGNORECASE)
AGENT_MODELS = frozenset(m.key for m in load_catalog(CATALOG).models("claude")) | {"inherit"}
AGENT_EFFORTS = frozenset({"low", "medium", "high"})
FULL_MODEL_ID = re.compile(r"^claude-[a-z0-9][a-z0-9.-]*$")
REFERENCE_TOC_THRESHOLD = 100
CONTENTS_WITHIN_LINES = 15  # "near the top"
CONTENTS_HEADING = re.compile(r"^## Contents\s*$")
# Frontmatter keys whose `[a, b]` value is a list; elsewhere brackets stay text (argument-hint).
LIST_KEYS = {"tools", "disallowedTools", "skills"}
BLOCK_SCALAR = re.compile(r"^[|>][+-]?\d?$")
# Markdown link targets (fragment and title dropped); local ones name references/ or scripts/,
# optionally behind ./ or ../ steps.
LINK_TARGET = re.compile(r"\]\(([^)\s#]+)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
LOCAL_PREFIX = re.compile(r"^(?:\.{1,2}/)*(?:references|scripts)/")
# Fenced blocks and inline code show example syntax, not links.
CODE = re.compile(r"(```|~~~).*?\1|`[^`\n]*`", re.DOTALL)
# `agent-skills:<name>` mentions in commands.
PLUGIN_REF = re.compile(r"agent-skills:([a-z0-9-]+)")
# Names in an eval grader pattern: `skill\W{1,8}(agent-skills:)?name` or `(a|b|c)`; `subagent_type…` likewise.
GRADER_NAMES = re.compile(
    r"(skill|subagent_type)\\W[{},\d*+?]*\(agent-skills:\)\?(\([^)]*\)|[A-Za-z0-9-]+)"
)

# Parsed frontmatter: text values, or a list of names for list keys.
Frontmatter = dict


class FrontmatterError(ValueError):
    """Frontmatter that the mini-parser would misread."""


# Paths installed users rely on (ADR 0026): moving one breaks cloud-setup.sh, the skills' printed paths or the READMEs' links.
CATALOGS = [
    ".claude-plugin/marketplace.json",
    ".github/plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
]
PUBLIC_PATHS = [
    *CATALOGS,
    "user-config/offload-policy.md",
    "user-config/routing.md",
    "user-agents/Explore.md",
    "LICENSE",
]
# README anchors other READMEs and the docs link to (ADR 0026).
PUBLIC_README_HEADINGS = ["## Install", "## Update", "## Develop", "## Recommended prompt"]

# Per-plugin versions (ADR 0027): plugin.json is the single source; pre-release suffixes such as `-rc.1` are allowed.
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
# A tag `<plugin>-vX.Y.Z` marks a release; the agent-skills release also ships these generated or shared folders.
TAG_VERSION = re.compile(r"^(?P<name>.+)-v(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")
EXTRA_RELEASE_PATHS = {"agent-skills": ["ports/", "user-config/", "user-agents/"]}


QUOTE_PAIR_LEN = 2  # opening and closing quote
MIN_TABLE_ROWS = 2  # header and separator


def unquote(value: str) -> str:
    """Strip one pair of matching quotes around a scalar (YAML allows 'x' and "x")."""
    if (
        len(value) >= QUOTE_PAIR_LEN
        and value[0] == value[-1]
        and value[0] in "'\""
        and value[0] not in value[1:-1]
    ):
        return value[1:-1]
    return value


def frontmatter_lines(text: str) -> list[str]:
    """Lines between the opening and closing '---'; FrontmatterError when either is missing."""
    if not text.startswith("---\n"):
        raise FrontmatterError("missing frontmatter: the file must start with '---'")
    end = text.find("\n---", 4)
    if end == -1:
        raise FrontmatterError("unterminated frontmatter: no closing '---'")
    return text[4:end].splitlines()


def assign_frontmatter_value(data: Frontmatter, key: str, value: str) -> str | None:
    """Store one `key: value`; return the key when it opens a block list."""
    if BLOCK_SCALAR.match(value):
        raise FrontmatterError(
            f"'{key}' uses a YAML block scalar ('{value}'): write the value on one line"
        )
    if key in LIST_KEYS and value.startswith("[") and value.endswith("]"):
        # Inline list: [a, b, c]
        data[key] = [unquote(v.strip()) for v in value[1:-1].split(",") if v.strip()]
        return None
    if not value:
        # Start of a block list.
        data[key] = []
        return key
    data[key] = unquote(value)
    return None


def parse_frontmatter_line(raw: str, data: Frontmatter, current_list: str | None) -> str | None:
    """Apply one frontmatter line to `data`; return the key still collecting "- item" lines."""
    line = raw.rstrip()
    if not line or line.lstrip().startswith("#"):
        return current_list
    # Continuation item of a block list ("  - foo").
    if current_list and line.lstrip().startswith("- "):
        data[current_list].append(unquote(line.lstrip()[2:].strip()))  # type: ignore[union-attr]
        return current_list
    if line[0] in " \t":
        raise FrontmatterError(
            f"cannot read indented line '{line.strip()}': keep each value on one line"
        )
    key, sep, value = line.partition(":")
    if not sep:
        raise FrontmatterError(f"cannot read line '{line}': expected 'key: value'")
    return assign_frontmatter_value(data, key.strip(), value.strip())


def parse_frontmatter(text: str) -> Frontmatter:
    """Parse the YAML subset used here: `key: value`, `key: [a, b]` and `- item` lists, quotes stripped.

    Raises FrontmatterError for what it cannot read faithfully: block scalars (`|`, `>`), values
    continued on indented lines, lines that are not `key: value`, a missing or unterminated block.
    """
    data: Frontmatter = {}
    current_list: str | None = None  # key currently collecting "- item" lines
    for raw in frontmatter_lines(text):
        current_list = parse_frontmatter_line(raw, data, current_list)
    return data


def load_markdown(path: Path, errors: list[str]) -> tuple[str, Frontmatter | None]:
    """Read a Markdown file with its frontmatter; unreadable frontmatter is reported and returned as None."""
    text = path.read_text(encoding="utf-8")
    try:
        return text, parse_frontmatter(text)
    except FrontmatterError as exc:
        errors.append(f"{path.relative_to(ROOT)}: {exc}")
        return text, None


def as_list(value: object) -> list[str]:
    """Frontmatter list value (`[a, b]`, `- a` lines, or a comma-separated string) as a list of names."""
    if isinstance(value, list):
        return [v for v in value if v]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def is_true(value: object) -> bool:
    """YAML true as the mini-parser sees it."""
    return isinstance(value, str) and value.lower() == "true"


def check_description(rel: Path, desc: object, errors: list[str]) -> None:
    """N2: description = what it does + when to use it, third person, bounded length."""
    if not isinstance(desc, str) or not desc:
        errors.append(f"{rel}: missing 'description'")
        return
    trigger = TRIGGER.search(desc)
    if not trigger:
        errors.append(f"{rel}: description must state its trigger ('Use when…')")
    elif trigger.start() == 0:
        errors.append(f"{rel}: description must say what it does before 'Use when…'")
    if len(desc) > DESCRIPTION_MAX:
        errors.append(f"{rel}: description {len(desc)} chars > {DESCRIPTION_MAX}")
    person = PERSON.search(
        QUOTED.sub("", desc)
    )  # quoted user phrases are trigger terms, not the description speaking
    if person:
        errors.append(f"{rel}: description must be third person (found '{person.group(0)}')")


def check_proactive(rel: Path, desc: object, is_worker: bool, errors: list[str]) -> None:
    """ADR 0010: only cheap offload workers may say "Use proactively" (it raises auto-delegation)."""
    if isinstance(desc, str) and PROACTIVE.search(desc) and not is_worker:
        errors.append(f"{rel}: only offload workers may say 'Use proactively' (ADR 0010)")


def check_line_budget(rel: Path, text: str, limit: int, errors: list[str]) -> None:
    """N1: SKILL.md <= 150 lines, agent <= 120."""
    lines = len(text.splitlines())
    if lines > limit:
        errors.append(f"{rel}: {lines} lines > {limit}")


def check_reference_depth(skill_dir: Path, errors: list[str]) -> None:
    """N1: detail lives in references/ one level deep, so no folders inside it."""
    errors.extend(
        f"{sub.relative_to(ROOT)}: nested folder in references/ (keep it one level deep)"
        for sub in sorted(p for p in (skill_dir / "references").rglob("*") if p.is_dir())
    )


def check_reference_toc(skill_dir: Path, errors: list[str]) -> None:
    """N1: reference files over 100 lines open with a `## Contents` heading (partial reads see scope)."""
    for ref in sorted((skill_dir / "references").rglob("*.md")):
        lines = ref.read_text(encoding="utf-8").splitlines()
        near_top = lines[:CONTENTS_WITHIN_LINES]
        if len(lines) > REFERENCE_TOC_THRESHOLD and not any(
            CONTENTS_HEADING.match(line) for line in near_top
        ):
            errors.append(
                f"{ref.relative_to(ROOT)}: > {REFERENCE_TOC_THRESHOLD} lines without a '## Contents' "
                f"heading in the first {CONTENTS_WITHIN_LINES}"
            )


def is_local_link(target: str, in_refs: bool) -> bool:
    """A link target that points inside the repository (inside a reference a bare `other.md` counts)."""
    if SCHEME.match(target) or target.startswith("/"):
        return False
    return bool(LOCAL_PREFIX.match(target) or (in_refs and target.endswith(".md")))


def check_links(skill_dir: Path, errors: list[str]) -> None:
    """N1: local links resolve, and a reference never links another reference (one level deep)."""
    refs = (skill_dir / "references").resolve()
    for md in sorted(skill_dir.rglob("*.md")):
        in_refs = refs in md.resolve().parents
        for target in LINK_TARGET.findall(CODE.sub("", md.read_text(encoding="utf-8"))):
            if not is_local_link(target, in_refs):
                continue
            found = next(
                (p.resolve() for p in (md.parent / target, skill_dir / target) if p.exists()), None
            )
            if found is None:
                errors.append(f"{md.relative_to(ROOT)}: broken link '{target}'")
            elif in_refs and refs in found.parents and found != md.resolve():
                errors.append(
                    f"{md.relative_to(ROOT)}: links another reference '{target}' (link it from SKILL.md)"
                )


def plugin_dirs() -> list[Path]:
    """Every plugin folder that ships skills or agents: the general rules run over all of them."""
    return sorted(
        p
        for p in (ROOT / "plugins").glob("*/")
        if (p / "skills").is_dir() or (p / "agents").is_dir()
    )


def check_skills(errors: list[str], plugin: Path) -> set[str]:
    """Validate every skill directory of a plugin and return the set of skill names found."""
    names: set[str] = set()
    for skill_md in sorted(plugin.glob("skills/*/SKILL.md")):
        skill_dir = skill_md.parent
        rel = skill_md.relative_to(ROOT)
        names.add(skill_dir.name)
        text, fm = load_markdown(skill_md, errors)
        if fm is not None:
            if fm.get("name") != skill_dir.name:
                errors.append(f"{rel}: frontmatter name must be '{skill_dir.name}'")
            if not NAME_RE.match(skill_dir.name):
                errors.append(
                    f"{rel}: name must be <= 64 chars of lowercase letters, digits, hyphens"
                )
            check_description(rel, fm.get("description"), errors)
            check_proactive(
                rel, fm.get("description"), False, errors
            )  # repo-wide: only workers (ADR 0007, 0010)
        check_line_budget(rel, text, SKILL_MAX_LINES, errors)
        check_reference_depth(skill_dir, errors)
        check_reference_toc(skill_dir, errors)
        check_links(skill_dir, errors)
    return names


def check_agent_rules(rel: Path, fm: Frontmatter, skill_names: set[str], errors: list[str]) -> None:
    """ADR 0010: the agent-frontmatter rules shared with scripts/port.py: model, effort, maxTurns, omitClaudeMd, preloads."""
    model = fm.get("model")
    if not isinstance(model, str) or not (model in AGENT_MODELS or FULL_MODEL_ID.match(model)):
        allowed = " | ".join(sorted(AGENT_MODELS))
        errors.append(f"{rel}: 'model' must be {allowed} or a full claude- id (got {model!r})")
    effort = fm.get("effort")
    if not effort:
        errors.append(f"{rel}: missing 'effort'")
    elif not isinstance(effort, str) or effort not in AGENT_EFFORTS:
        errors.append(
            f"{rel}: 'effort' must be {' | '.join(sorted(AGENT_EFFORTS))} (got {effort!r})"
        )
    turns = fm.get("maxTurns")
    if turns is not None and not (
        isinstance(turns, str) and re.fullmatch(r"[0-9]+", turns) and int(turns) > 0
    ):
        errors.append(f"{rel}: 'maxTurns' must be a positive integer (got {turns!r})")
    if fm.get("omitClaudeMd") not in {None, "true", "false"}:
        errors.append(f"{rel}: 'omitClaudeMd' must be true or false")
    errors.extend(
        f"{rel}: preloads unknown skill '{skill}'"
        for skill in as_list(fm.get("skills"))
        if skill not in skill_names
    )


def check_max_turns(rel: Path, name: str, fm: Frontmatter, errors: list[str]) -> None:
    """ADR 0010: workers cap their turns, so a stuck cheap worker cannot burn tokens unseen."""
    if name in WORKERS and fm.get("maxTurns") is None:
        errors.append(f"{rel}: worker must set 'maxTurns' to a positive integer")


def check_read_only(rel: Path, fm: Frontmatter, errors: list[str]) -> None:
    """N7 + ADR 0010: "Read-only" agents block write tools and skip CLAUDE.md in config, not in prompt text."""
    desc = fm.get("description")
    if not isinstance(desc, str) or "Read-only" not in desc:
        return
    unblocked = WRITE_TOOLS - set(as_list(fm.get("disallowedTools")))
    if unblocked:
        errors.append(
            f"{rel}: Read-only agent must list {', '.join(sorted(unblocked))} in disallowedTools"
        )
    granted = WRITE_TOOLS & set(as_list(fm.get("tools")))
    if granted:
        errors.append(
            f"{rel}: Read-only agent must not grant {', '.join(sorted(granted))} in tools"
        )
    if not is_true(fm.get("omitClaudeMd")):
        errors.append(f"{rel}: Read-only agent must set omitClaudeMd: true")


def check_workers_exist(agent_names: set[str], errors: list[str]) -> None:
    """ADR 0010: each name in the validator's worker set has an agent file, so the set cannot go stale."""
    errors.extend(
        f"{(PLUGIN / 'agents' / f'{name}.md').relative_to(ROOT)}: worker '{name}' has no agent file"
        for name in sorted(WORKERS - agent_names)
    )


def check_agent_frontmatter(
    rel: Path, name: str, fm: Frontmatter, scope: tuple[bool, set[str]], errors: list[str]
) -> None:
    """Frontmatter rules of one agent; `scope` is (agent-skills plugin?, skill names for preloads)."""
    own, skill_names = scope
    if fm.get("name") != name:
        errors.append(f"{rel}: frontmatter name must be '{name}'")
    if not fm.get("tools"):
        errors.append(f"{rel}: missing 'tools'")
    check_description(rel, fm.get("description"), errors)
    check_proactive(
        rel, fm.get("description"), own and name in WORKERS, errors
    )  # workers live in agent-skills
    check_agent_rules(rel, fm, skill_names, errors)
    if own:
        check_max_turns(rel, name, fm, errors)
    check_read_only(rel, fm, errors)


def check_agents(errors: list[str], skill_names: set[str], plugin: Path) -> set[str]:
    """Validate every agent of a plugin, including preloads from its own skills; return the agent names found.

    Workers, their maxTurns and "Use proactively" are agent-skills scope; the other rules apply to every plugin."""
    names: set[str] = set()
    own = plugin == PLUGIN
    for agent_md in sorted(plugin.glob("agents/*.md")):
        name = agent_md.stem
        rel = agent_md.relative_to(ROOT)
        names.add(name)
        text, fm = load_markdown(agent_md, errors)
        if fm is not None:
            check_agent_frontmatter(rel, name, fm, (own, skill_names), errors)
        check_line_budget(rel, text, AGENT_MAX_LINES, errors)
    if own:
        check_workers_exist(names, errors)
    return names


def check_command_shape(rel: Path, text: str, fm: Frontmatter, errors: list[str]) -> None:
    """N8: a command is a user-only entry point that shows a hint and passes $ARGUMENTS on."""
    if not fm.get("description"):
        errors.append(f"{rel}: missing 'description'")
    if not is_true(fm.get("disable-model-invocation")):
        errors.append(f"{rel}: commands must set disable-model-invocation: true (user-only)")
    if not fm.get("argument-hint"):
        errors.append(f"{rel}: missing 'argument-hint'")
    if "$ARGUMENTS" not in text.partition("\n---\n")[2]:
        errors.append(f"{rel}: body must use $ARGUMENTS")


def check_agent_commands(agent_names: set[str], named: set[str], errors: list[str]) -> None:
    """N8: every agent except the offload workers has an explicit command that names it."""
    errors.extend(
        f"{(PLUGIN / 'agents' / f'{name}.md').relative_to(ROOT)}: no command names 'agent-skills:{name}'"
        for name in sorted(agent_names - WORKERS - named)
    )


def check_offload_rows(errors: list[str]) -> None:
    """N9: every offload worker has a row in commands/offload.md."""
    rel = OFFLOAD_COMMAND.relative_to(ROOT)
    if not OFFLOAD_COMMAND.exists():
        errors.append(f"{rel}: missing")
        return
    text = OFFLOAD_COMMAND.read_text(encoding="utf-8")
    errors.extend(
        f"{rel}: no row for worker 'agent-skills:{name}'"
        for name in sorted(WORKERS)
        if f"agent-skills:{name}" not in text
    )


def check_commands(errors: list[str], skill_names: set[str], agent_names: set[str]) -> None:
    """N8: commands are user-only entry points that name existing agents or skills."""
    named: set[str] = set()
    for cmd in sorted(PLUGIN.glob("commands/*.md")):
        rel = cmd.relative_to(ROOT)
        text, fm = load_markdown(cmd, errors)
        if fm is not None:
            check_command_shape(rel, text, fm, errors)
        for ref in PLUGIN_REF.findall(text):
            named.add(ref)
            if ref not in agent_names and ref not in skill_names:
                errors.append(f"{rel}: references unknown agent/skill '{ref}'")
    check_agent_commands(agent_names, named, errors)
    check_offload_rows(errors)


def grader_pattern(path: Path) -> str | None:
    """The top-level `pattern:` of a grader's frontmatter with its quotes stripped, or None."""
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        if line.startswith("---"):
            break
        if line.startswith("pattern:"):
            return unquote(line.partition(":")[2].strip())
    return None


def grader_names(pattern: str) -> tuple[set[str], set[str]]:
    """(skill names, agent names) that a grader pattern matches on."""
    skills: set[str] = set()
    agents: set[str] = set()
    for kind, group in GRADER_NAMES.findall(pattern):
        (skills if kind == "skill" else agents).update(group.strip("()").split("|"))
    return skills, agents


def check_eval_graders(errors: list[str], skill_names: set[str], agent_names: set[str]) -> None:
    """N6: eval graders name existing skills/agents; no-trigger graders name all of them (a new one cannot slip by)."""
    evals = PLUGIN / "evals"
    for grader in sorted(evals.glob("*/*/graders/*.md")):
        pattern = grader_pattern(grader)
        if pattern is None:
            continue
        rel = grader.relative_to(ROOT)
        skills, agents = grader_names(pattern)
        errors.extend(
            f"{rel}: pattern names unknown skill '{name}'" for name in sorted(skills - skill_names)
        )
        errors.extend(
            f"{rel}: pattern names unknown agent '{name}'" for name in sorted(agents - agent_names)
        )
        if grader.relative_to(evals).parts[0] == "no-trigger":
            missing_skills, missing_agents = (
                sorted(skill_names - skills),
                sorted(agent_names - agents),
            )
            if missing_skills:
                errors.append(
                    f"{rel}: no-trigger pattern misses skill(s) {', '.join(missing_skills)}"
                )
            if missing_agents:
                errors.append(
                    f"{rel}: no-trigger pattern misses agent(s) {', '.join(missing_agents)}"
                )


def block_scalar(text: str, key: str) -> str | None:
    """Decode the `key: |` literal block scalar of a YAML file without PyYAML (trailing newlines dropped)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        head = re.match(rf"^( *){re.escape(key)}:\s*\|[+-]?\s*$", line)
        if not head:
            continue
        key_indent, indent, body = len(head.group(1)), None, []
        for nxt in lines[i + 1 :]:
            if not nxt.strip():
                body.append(nxt[indent:] if indent is not None else "")
                continue
            lead = len(nxt) - len(nxt.lstrip(" "))
            if lead <= key_indent or (indent is not None and lead < indent):
                break
            indent = lead if indent is None else indent
            body.append(nxt[indent:])
        return "\n".join(body).rstrip("\n")
    return None


def first_difference(a: str, b: str) -> int:
    """1-based number of the first line where two texts differ."""
    la, lb = a.splitlines(), b.splitlines()
    for number, (x, y) in enumerate(zip(la, lb, strict=False), 1):
        if x != y:
            return number
    return min(len(la), len(lb)) + 1


def check_offload_policy(errors: list[str]) -> None:
    """ADR 0010: with-policy offload evals embed user-config/offload-policy.md verbatim (they measure what ships)."""
    cases = sorted((PLUGIN / "evals" / "offload").glob("*-with-policy/case.yaml"))
    if not cases:
        return
    if not POLICY.exists():
        errors.append(f"{POLICY.relative_to(ROOT)}: missing (offload with-policy evals embed it)")
        return
    expected = POLICY.read_text(encoding="utf-8").rstrip("\n")
    for case in cases:
        rel = case.relative_to(ROOT)
        embedded = block_scalar(case.read_text(encoding="utf-8"), "append_system_prompt")
        if embedded is None:
            errors.append(
                f"{rel}: no 'append_system_prompt: |' block (it must embed the offload policy)"
            )
        elif embedded != expected:
            line = first_difference(embedded, expected)
            errors.append(
                f"{rel}: append_system_prompt differs from {POLICY.relative_to(ROOT)} (first difference at line {line})"
            )


def check_fragments(errors: list[str]) -> None:
    """Marked blocks equal their shared/fragments/<id>.md; shared text is not copied outside a block."""
    errors.extend(fragments.check(ROOT))


def check_memory_offload(errors: list[str]) -> None:
    """ADR 0030: the memory plugin's offload table, which the owner pastes into CLAUDE.md, has a row for every agent."""
    table = ROOT / "plugins" / "memory" / "user-config" / "offload-policy.md"
    text = table.read_text(encoding="utf-8") if table.is_file() else ""
    rows = {
        m
        for line in text.splitlines()
        if line.startswith("|")
        for m in re.findall(r"`memory:([\w-]+)`", line)
    }
    agents = {p.stem for p in (ROOT / "plugins" / "memory" / "agents").glob("*.md")}
    errors.extend(
        f"{table.relative_to(ROOT)}: no row for `memory:{name}` (ADR 0030)"
        for name in sorted(agents - rows)
    )
    errors.extend(
        f"{table.relative_to(ROOT)}: row for `memory:{name}`, which is not an agent (ADR 0030)"
        for name in sorted(rows - agents)
    )


def check_ports(errors: list[str]) -> None:
    """ADR 0015: the Copilot and Codex ports are current and equivalent to the Claude sources (scripts/port.py --check)."""
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "port.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    if run.returncode != 0:
        lines = run.stdout.splitlines() or run.stderr.strip().splitlines()[-1:]
        already = set(
            errors
        )  # validate.py reports the shared agent rules itself; port's own repeats stay
        errors.extend(line for line in lines if line.strip() and line not in already)


def readme_table(text: str, heading: str, first_header: str) -> list[dict[str, str]] | None:
    """Rows, keyed by column header, of the first table under the `###` heading in `## Catalog`."""
    catalog = re.search(r"^## Catalog\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    section = re.search(
        rf"^### {heading}\b.*?$(.*?)(?=^###? |\Z)",
        catalog.group(1) if catalog else "",
        re.MULTILINE | re.DOTALL,
    )
    if not section:
        return None
    rows = [
        [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        for line in section.group(1).splitlines()
        if line.startswith("|")
    ]
    if len(rows) < MIN_TABLE_ROWS or rows[0][0] != first_header:
        return None
    return [dict(zip(rows[0], row, strict=False)) for row in rows[MIN_TABLE_ROWS:]]


def backticked(cell: str, pattern: str = r"`([^`]+)`") -> str | None:
    """The name a catalog cell starts with: the first backticked text, or the given pattern's group."""
    match = re.search(pattern, cell)
    return match.group(1) if match else None


def compare_names(table: str, listed: list[str], actual: set[str], errors: list[str]) -> None:
    """Report README rows without a plugin item (extra) and plugin items without a row (missing)."""
    errors.extend(
        f"README.md: {table} table has extra row '{name}' (no such item in the plugin)"
        for name in sorted(set(listed) - actual)
    )
    errors.extend(
        f"README.md: {table} table is missing a row for '{name}'"
        for name in sorted(actual - set(listed))
    )


def check_agent_row(name: str, row: dict[str, str], agent_md: Path, errors: list[str]) -> None:
    """One README Agents row against the agent's frontmatter: `Model` and `Preloads`."""
    fm = parse_frontmatter(agent_md.read_text(encoding="utf-8"))
    model, wanted = row.get("Model"), set(as_list(fm.get("skills")))
    preloads = {v.strip() for v in row.get("Preloads", "").split(",") if v.strip() not in {"", "—"}}
    if model != fm.get("model"):
        errors.append(
            f"README.md: Agents table: '{name}' has model '{model}', frontmatter says '{fm.get('model')}'"
        )
    if preloads != wanted:
        errors.append(
            f"README.md: Agents table: '{name}' preloads {sorted(preloads)}, frontmatter says {sorted(wanted)}"
        )


def check_agents_table(table: list[dict[str, str]], errors: list[str]) -> None:
    agents = {p.stem: p for p in PLUGIN.glob("agents/*.md")}
    rows = {backticked(row["Agent"]): row for row in table}
    compare_names("Agents", [n for n in rows if n], set(agents), errors)
    for name, row in rows.items():
        if name in agents:
            check_agent_row(name, row, agents[name], errors)


def check_skills_table(table: list[dict[str, str]], errors: list[str]) -> None:
    listed = [backticked(row["Skill"]) for row in table]
    compare_names(
        "Skills",
        [n for n in listed if n],
        {p.parent.name for p in PLUGIN.glob("skills/*/SKILL.md")},
        errors,
    )


def check_commands_table(table: list[dict[str, str]], errors: list[str]) -> None:
    listed = [backticked(row["Command"], r"agent-skills:([^\s`]+)") for row in table]
    compare_names(
        "Commands",
        [n for n in listed if n],
        {p.stem for p in PLUGIN.glob("commands/*.md")},
        errors,
    )


def check_readme_catalog(errors: list[str]) -> None:
    """README catalog, CLAUDE.md § Where a change goes: README `## Catalog` tables match the plugin.

    Agents: names, `Model` and `Preloads`; Skills and Commands: names. Prose columns stay unchecked.
    """
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    checks = (
        ("Agents", "Agent", check_agents_table),
        ("Skills", "Skill", check_skills_table),
        ("Commands", "Command", check_commands_table),
    )
    for table, first_header, check in checks:
        rows = readme_table(text, table, first_header)
        if rows is None:
            errors.append(
                f"README.md: no '### {table}' table under '## Catalog' with the expected first column"
            )
        else:
            check(rows, errors)


def catalog_sources(rel: str) -> list[str]:
    """`source` paths of one catalog; a source is a string or an object with a `path`."""
    path = ROOT / rel
    if not path.is_file():
        return []
    try:
        plugins = json.loads(path.read_text(encoding="utf-8")).get("plugins", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    sources = []
    for entry in plugins:
        source = entry.get("source")
        sources.append(source.get("path", "") if isinstance(source, dict) else source or "")
    return [s for s in sources if s]


def check_public_paths(errors: list[str]) -> None:
    """ADR 0026: the paths installed users rely on exist, and the README keeps the anchors other docs link to."""
    wanted = list(PUBLIC_PATHS)
    for rel in CATALOGS:
        wanted.extend(s.removeprefix("./") for s in catalog_sources(rel))
    errors.extend(
        f"{rel}: public path is missing (ADR 0026)"
        for rel in dict.fromkeys(wanted)
        if not (ROOT / rel).exists()
    )
    readme = ROOT / "README.md"
    lines = readme.read_text(encoding="utf-8").splitlines() if readme.is_file() else []
    errors.extend(
        f"README.md: missing heading '{heading}' (ADR 0026)"
        for heading in PUBLIC_README_HEADINGS
        if heading not in (line.rstrip() for line in lines)
    )


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
    )


def version_key(version: str) -> tuple[tuple[int, ...], bool, str]:
    """Sort key: numeric parts, then a release after its own pre-releases."""
    core, _, pre = version.partition("-")
    return tuple(int(n) for n in core.split(".")), not pre, pre


def latest_tag(name: str, stdout: str) -> tuple[str, str] | None:
    """(tag, version) of the newest `<name>-vX.Y.Z` tag in `git tag --list` output, or None."""
    tags = {}
    for tag in stdout.split():
        match = TAG_VERSION.match(tag)
        if match and match["name"] == name:
            tags[tag] = match["version"]
    if not tags:
        return None
    tag = max(tags, key=lambda t: version_key(tags[t]))
    return tag, tags[tag]


def check_tag_manifest(manifest: str, tag: str, tag_version: str, errors: list[str]) -> None:
    """The plugin.json committed at the tag carries the tag's version."""
    shown = git("show", f"{tag}:{manifest}")
    try:
        at_tag = json.loads(shown.stdout).get("version") if shown.returncode == 0 else None
    except json.JSONDecodeError:
        at_tag = None
    if at_tag != tag_version:
        errors.append(
            f"{manifest}: at tag {tag} the version is {at_tag!r}, the tag says {tag_version!r}"
        )


def check_release_tag(name: str, version: str | None, errors: list[str]) -> None:
    """ADR 0027, `--release`: the latest tag of the plugin matches its plugin.json, and an unchanged version has no changes."""
    listed = git("tag", "--list", f"{name}-v*")
    if listed.returncode != 0:
        errors.append(
            f"{name}: cannot list git tags ({listed.stderr.strip()}); --release needs the git repository"
        )
        return
    latest = latest_tag(name, listed.stdout)
    if latest is None:
        return
    tag, tag_version = latest
    manifest = f"plugins/{name}/.claude-plugin/plugin.json"
    check_tag_manifest(manifest, tag, tag_version, errors)
    if version and version_key(version) < version_key(tag_version):
        errors.append(f"{manifest}: version {version} is below the latest tag {tag}")
    if version == tag_version:
        paths = [f"plugins/{name}", *EXTRA_RELEASE_PATHS.get(name, [])]
        # Against the working tree, so uncommitted edits count too.
        if git("diff", "--quiet", tag, "--", *paths).returncode != 0:
            errors.append(
                f"{name}: changes since {tag} under {', '.join(paths)} but the version is still {version}: bump it"
            )


STATE_PLAN = Path(
    "docs/superpowers/plans/2026-11-17-memory-plugin.md"
)  # relative: tests patch ROOT
STATE_RELEASED = re.compile(
    r"^\|\s*\**Released\**\s*\|\s*`memory`\s+v?([0-9][0-9A-Za-z.+-]*)", re.MULTILINE
)


def check_state_table_version(errors: list[str]) -> None:
    """The memory plan's state table, which agents resuming memory work read first, names the released version."""
    plan = ROOT / STATE_PLAN
    manifest = ROOT / "plugins" / "memory" / ".claude-plugin" / "plugin.json"
    if not plan.is_file() or not manifest.is_file():
        return
    rel = plan.relative_to(ROOT).as_posix()
    match = STATE_RELEASED.search(plan.read_text(encoding="utf-8"))
    version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
    if not match:  # a reworded row must not switch the check off
        errors.append(f"{rel}: no '| Released | `memory` X.Y.Z' row in the state table")
    elif match.group(1) != version:
        errors.append(
            f"{rel}: state table says released {match.group(1)}, plugin.json says {version}"
        )


def check_catalog_versions(errors: list[str]) -> None:
    """Catalog entries carry no `version`: plugin.json is the only source."""
    for rel in CATALOGS:
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            plugins = json.loads(path.read_text(encoding="utf-8")).get("plugins", [])
        except (json.JSONDecodeError, AttributeError):
            errors.append(f"{rel}: not valid JSON")
            continue
        errors.extend(
            f"{rel}: entry '{entry.get('name')}' carries 'version'; plugin.json is the only source (ADR 0027)"
            for entry in plugins
            if "version" in entry
        )


def check_changelog_heading(name: str, version: str | None, errors: list[str]) -> None:
    """The plugin's CHANGELOG exists and has a heading for its version."""
    changelog = ROOT / "plugins" / name / "CHANGELOG.md"
    heading = rf"^## \[{re.escape(version or '')}\] - \d{{4}}-\d{{2}}-\d{{2}}\s*$"
    if not changelog.is_file():
        errors.append(f"plugins/{name}/CHANGELOG.md: missing (ADR 0027)")
    elif version and not re.search(heading, changelog.read_text(encoding="utf-8"), re.MULTILINE):
        errors.append(
            f"plugins/{name}/CHANGELOG.md: no heading '## [{version}] - YYYY-MM-DD' (ADR 0027)"
        )


def check_plugin_version(name: str, release: bool, errors: list[str]) -> None:
    """One catalog plugin: SemVer in plugin.json, a CHANGELOG heading for it, and the tag check on a release."""
    manifest = f"plugins/{name}/.claude-plugin/plugin.json"
    try:
        version = json.loads((ROOT / manifest).read_text(encoding="utf-8")).get("version")
    except (OSError, json.JSONDecodeError):
        errors.append(f"{manifest}: missing or not valid JSON")
        return
    if not isinstance(version, str) or not SEMVER.match(version):
        errors.append(f"{manifest}: 'version' is {version!r}, expected SemVer X.Y.Z (ADR 0027)")
        version = None
    check_changelog_heading(name, version, errors)
    if release:
        check_release_tag(name, version, errors)


def check_versions(errors: list[str], release: bool) -> None:
    """ADR 0027: each plugin has a SemVer version in plugin.json and a CHANGELOG heading for it; catalogs carry no version."""
    check_catalog_versions(errors)
    try:
        entries = json.loads((ROOT / CATALOGS[0]).read_text(encoding="utf-8")).get("plugins", [])
    except (OSError, json.JSONDecodeError):
        return
    for entry in entries:
        check_plugin_version(entry.get("name", ""), release, errors)


def read_json(rel: str) -> dict[str, object] | None:
    try:
        data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def check_codex_plugin(errors: list[str], name: str) -> None:
    manifest = f"plugins/{name}/.codex-plugin/plugin.json"
    got = read_json(manifest)
    if got is None:
        errors.append(f"{manifest}: missing or not valid JSON (ADR 0036)")
        return
    claude = read_json(f"plugins/{name}/.claude-plugin/plugin.json") or {}
    for key in ("name", "version", "description"):
        want = name if key == "name" else claude.get(key)
        if got.get(key) != want:
            errors.append(f"{manifest}: '{key}' is {got.get(key)!r}, expected {want!r} (ADR 0036)")
    hooks = got.get("hooks")
    if not isinstance(hooks, str) or not (ROOT / "plugins" / name / hooks).is_file():
        errors.append(
            f"{manifest}: 'hooks' {hooks!r} does not name a file under plugins/{name} (ADR 0036)"
        )


def check_codex_manifest(errors: list[str]) -> None:
    """ADR 0036: a plugin the Codex catalog serves from its source folder has a `.codex-plugin/plugin.json` that mirrors its Claude manifest."""
    listed = (read_json(".agents/plugins/marketplace.json") or {}).get("plugins")
    for entry in listed if isinstance(listed, list) else []:
        if entry.get("name") != "agent-skills":  # a generated port, checked by port.py
            check_codex_plugin(errors, str(entry.get("name")))


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--release",
        action="store_true",
        help="also compare each plugin with its latest git tag (ADR 0027)",
    )
    release = parser.parse_args().release
    errors: list[str] = []
    skills: set[str] = set()
    agents: set[str] = set()
    total_skills = total_agents = 0
    for plugin in plugin_dirs():
        plugin_skills = check_skills(errors, plugin)
        plugin_agents = check_agents(errors, plugin_skills, plugin)
        total_skills += len(plugin_skills)
        total_agents += len(plugin_agents)
        if plugin == PLUGIN:
            skills, agents = plugin_skills, plugin_agents
    check_commands(errors, skills, agents)
    check_eval_graders(errors, skills, agents)
    check_offload_policy(errors)
    check_memory_offload(errors)
    check_readme_catalog(errors)
    check_public_paths(errors)
    check_fragments(errors)
    check_versions(errors, release)
    check_codex_manifest(errors)
    check_state_table_version(errors)
    check_ports(errors)
    for err in errors:
        print(err)
    print(
        f"{'FAIL' if errors else 'OK'}: {total_skills} skills, {total_agents} agents, {len(errors)} errors"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
