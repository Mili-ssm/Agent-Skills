#!/usr/bin/env python3
"""Validate skills and agents against the repo contract (docs/requirements.md, N1-N2).

Checks:
  - Every skills/<name>/SKILL.md has frontmatter with `name` == <name> and a `description`
    that states its trigger ("Use when" / "Use to" / "Use before" / "Use after").
  - Every agents/<name>.md has `name` == <name>, `description`, `tools`.
  - Line budgets: SKILL.md <= 150, agent <= 120.
  - Relative links to references/ or scripts/ inside a skill point to existing files.
  - Skills listed in an agent's `skills:` frontmatter exist in skills/.

Standard library only so it runs in any fresh environment: `python3 scripts/validate.py`.
Exit code 0 = valid, 1 = at least one error (errors are printed one per line).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Repo root = parent of the scripts/ directory, independent of the current working directory.
ROOT = Path(__file__).resolve().parent.parent
SKILL_MAX_LINES = 150
AGENT_MAX_LINES = 120
# Accepted trigger openings for descriptions (N2).
TRIGGER = re.compile(r"\bUse (when|to|before|after)\b")
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


def check_skills(errors: list[str]) -> set[str]:
    """Validate every skill directory and return the set of skill names found."""
    names: set[str] = set()
    for skill_md in sorted(ROOT.glob("skills/*/SKILL.md")):
        skill_dir = skill_md.parent
        rel = skill_md.relative_to(ROOT)
        text = skill_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        names.add(skill_dir.name)
        if fm.get("name") != skill_dir.name:
            errors.append(f"{rel}: frontmatter name must be '{skill_dir.name}'")
        desc = fm.get("description", "")
        if not isinstance(desc, str) or not TRIGGER.search(desc):
            errors.append(f"{rel}: description must state its trigger ('Use when…')")
        lines = text.count("\n") + 1
        if lines > SKILL_MAX_LINES:
            errors.append(f"{rel}: {lines} lines > {SKILL_MAX_LINES}")
        # Every local link inside any markdown file of the skill must resolve.
        for md in skill_dir.rglob("*.md"):
            for target in LOCAL_LINK.findall(md.read_text(encoding="utf-8")):
                if not (skill_dir / target).exists():
                    errors.append(f"{md.relative_to(ROOT)}: broken link '{target}'")
    return names


def check_agents(errors: list[str], skill_names: set[str]) -> None:
    """Validate every agent definition, including its preloaded skills."""
    for agent_md in sorted(ROOT.glob("agents/*.md")):
        rel = agent_md.relative_to(ROOT)
        text = agent_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm.get("name") != agent_md.stem:
            errors.append(f"{rel}: frontmatter name must be '{agent_md.stem}'")
        for key in ("description", "tools"):
            if not fm.get(key):
                errors.append(f"{rel}: missing '{key}'")
        desc = fm.get("description", "")
        if isinstance(desc, str) and desc and not TRIGGER.search(desc):
            errors.append(f"{rel}: description must state its trigger ('Use when…')")
        lines = text.count("\n") + 1
        if lines > AGENT_MAX_LINES:
            errors.append(f"{rel}: {lines} lines > {AGENT_MAX_LINES}")
        preload = fm.get("skills", [])
        for skill in preload if isinstance(preload, list) else [preload]:
            if skill not in skill_names:
                errors.append(f"{rel}: preloads unknown skill '{skill}'")


def main() -> int:
    errors: list[str] = []
    skills = check_skills(errors)
    check_agents(errors, skills)
    for err in errors:
        print(err)
    agents = len(list(ROOT.glob("agents/*.md")))
    print(f"{'FAIL' if errors else 'OK'}: {len(skills)} skills, {agents} agents, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
