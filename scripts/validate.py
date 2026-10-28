#!/usr/bin/env python3
"""Validate skills and agents against the repo contract (docs/requirements.md, N1-N2).

Checks (Anthropic skill-authoring rules + repo contract):
  - Every skills/<name>/SKILL.md has frontmatter with `name` == <name> (<= 64 chars, lowercase,
    digits, hyphens) and a `description` that says what it does first, then its trigger
    ("Use when" / "Use to" / "Use before" / "Use after" / "Use proactively"), in third person, <= 1024 chars.
  - Reference files over 100 lines start with a `## Contents` section (partial reads see scope).
  - Every agents/<name>.md has `name` == <name>, `description`, `tools`.
  - Line budgets: SKILL.md <= 150, agent <= 120.
  - Relative links to references/ or scripts/ inside a skill point to existing files.
  - Skills listed in an agent's `skills:` frontmatter exist in skills/.
  - commands/*.md have a description, are user-only and reference existing agents/skills.

Standard library only so it runs in any fresh environment: `python3 scripts/validate.py`.
Exit code 0 = valid, 1 = at least one error (errors are printed one per line).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Repo root = parent of the scripts/ directory, independent of the current working directory.
ROOT = Path(__file__).resolve().parent.parent
# The agent-skills plugin lives in its own folder so the marketplace can list mods beside it (ADR 0011).
PLUGIN = ROOT / "plugins" / "agent-skills"
SKILL_MAX_LINES = 150
AGENT_MAX_LINES = 120
# Accepted trigger openings for descriptions (N2).
# "Use proactively" is reserved for cheap offload workers (ADR 0010).
TRIGGER = re.compile(r"\bUse (when|to|before|after|proactively)\b")
# Skill/agent name format and description limits from Anthropic's skill-authoring guide.
NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
DESCRIPTION_MAX = 1024
# First/second-person openings break discovery: descriptions are injected into the system prompt.
NOT_THIRD_PERSON = re.compile(r"\b(I can|I will|You can|you can)\b")
REFERENCE_TOC_THRESHOLD = 100
# Markdown links whose target starts with references/ or scripts/ (relative to the skill dir).
LOCAL_LINK = re.compile(r"\]\(((?:references|scripts)/[^)#\s]+)")


def parse_frontmatter(text: str) -> dict[str, str | list[str]]:
    """Parse the minimal YAML subset used here: `key: value` and `key: [a, b]` / `- item` lists."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    data: dict[str, str | list[str]] = {}
    current_list: str | None = None  # key currently collecting "- item" lines
    for raw in text[4:end].splitlines():
        line = raw.rstrip()
        if not line:
            continue
        # Continuation item of a block list ("  - foo").
        if current_list and line.lstrip().startswith("- "):
            data[current_list].append(line.lstrip()[2:].strip())  # type: ignore[union-attr]
            continue
        current_list = None
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            # Inline list: [a, b, c]
            data[key] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        elif value == "":
            # Start of a block list.
            data[key] = []
            current_list = key
        else:
            data[key] = value
    return data


def check_description(rel: Path, desc: object, errors: list[str]) -> None:
    """Description = what it does + when to use it, third person, bounded length."""
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
    if NOT_THIRD_PERSON.search(desc):
        errors.append(f"{rel}: description must be third person")


def check_skills(errors: list[str]) -> set[str]:
    """Validate every skill directory and return the set of skill names found."""
    names: set[str] = set()
    for skill_md in sorted(PLUGIN.glob("skills/*/SKILL.md")):
        skill_dir = skill_md.parent
        rel = skill_md.relative_to(ROOT)
        text = skill_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        names.add(skill_dir.name)
        if fm.get("name") != skill_dir.name:
            errors.append(f"{rel}: frontmatter name must be '{skill_dir.name}'")
        if not NAME_RE.match(skill_dir.name):
            errors.append(f"{rel}: name must be <= 64 chars of lowercase letters, digits, hyphens")
        check_description(rel, fm.get("description"), errors)
        lines = text.count("\n") + 1
        if lines > SKILL_MAX_LINES:
            errors.append(f"{rel}: {lines} lines > {SKILL_MAX_LINES}")
        # Long reference files need a table of contents near the top.
        for ref in sorted(skill_dir.glob("references/*.md")):
            ref_text = ref.read_text(encoding="utf-8")
            if ref_text.count("\n") + 1 > REFERENCE_TOC_THRESHOLD and "## Contents" not in ref_text[:600]:
                errors.append(f"{ref.relative_to(ROOT)}: > {REFERENCE_TOC_THRESHOLD} lines without '## Contents'")
        # Every local link inside any markdown file of the skill must resolve.
        for md in skill_dir.rglob("*.md"):
            for target in LOCAL_LINK.findall(md.read_text(encoding="utf-8")):
                if not (skill_dir / target).exists():
                    errors.append(f"{md.relative_to(ROOT)}: broken link '{target}'")
    return names


def check_agents(errors: list[str], skill_names: set[str]) -> None:
    """Validate every agent definition, including its preloaded skills."""
    for agent_md in sorted(PLUGIN.glob("agents/*.md")):
        rel = agent_md.relative_to(ROOT)
        text = agent_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm.get("name") != agent_md.stem:
            errors.append(f"{rel}: frontmatter name must be '{agent_md.stem}'")
        if not fm.get("tools"):
            errors.append(f"{rel}: missing 'tools'")
        check_description(rel, fm.get("description"), errors)
        lines = text.count("\n") + 1
        if lines > AGENT_MAX_LINES:
            errors.append(f"{rel}: {lines} lines > {AGENT_MAX_LINES}")
        preload = fm.get("skills", [])
        for skill in preload if isinstance(preload, list) else [preload]:
            if skill not in skill_names:
                errors.append(f"{rel}: preloads unknown skill '{skill}'")


def check_commands(errors: list[str], skill_names: set[str]) -> None:
    """Commands are user-only entry points that must reference existing agents or skills."""
    agent_names = {p.stem for p in PLUGIN.glob("agents/*.md")}
    for cmd in sorted(PLUGIN.glob("commands/*.md")):
        rel = cmd.relative_to(ROOT)
        text = cmd.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if not fm.get("description"):
            errors.append(f"{rel}: missing 'description'")
        if fm.get("disable-model-invocation") != "true":
            errors.append(f"{rel}: commands must set disable-model-invocation: true (user-only)")
        for ref in re.findall(r"agent-skills:([a-z0-9-]+)", text):
            if ref not in agent_names and ref not in skill_names:
                errors.append(f"{rel}: references unknown agent/skill '{ref}'")


def main() -> int:
    errors: list[str] = []
    skills = check_skills(errors)
    check_agents(errors, skills)
    check_commands(errors, skills)
    for err in errors:
        print(err)
    agents = len(list(PLUGIN.glob("agents/*.md")))
    print(f"{'FAIL' if errors else 'OK'}: {len(skills)} skills, {agents} agents, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
