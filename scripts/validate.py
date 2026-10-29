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
POLICY = ROOT / "user-config" / "offload-policy.md"
OFFLOAD_COMMAND = PLUGIN / "commands" / "offload.md"
SKILL_MAX_LINES = 150
AGENT_MAX_LINES = 120
# Cheap offload workers (ADR 0010): the only agents that may say "Use proactively"; each sets maxTurns and
# has a row in commands/offload.md. `Explore` is a user-scope agent (user-agents/), so it is not listed.
WORKERS = {"check-runner", "summarizer", "researcher", "implementer", "fixer", "ui-verifier"}
# Tools a "Read-only" agent must neither hold nor leave unblocked (N7).
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
# Accepted trigger openings for descriptions (N2).
TRIGGER = re.compile(r"\bUse (when|to|before|after|proactively)\b")
PROACTIVE = re.compile(r"\buse proactively\b", re.IGNORECASE)
# Skill/agent name format and description limits from Anthropic's skill-authoring guide.
NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
DESCRIPTION_MAX = 1024
# Descriptions are injected into the system prompt, so first/second person breaks discovery.
# "I" is matched in capitals only and skips "I/O"; the other pronouns match in any case.
PERSON = re.compile(r"(?-i:\bI\b(?!/))|\b(?:we|you|your|our)\b", re.IGNORECASE)
MODEL_ALIASES = {"haiku", "sonnet", "opus", "fable", "inherit"}
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
GRADER_NAMES = re.compile(r"(skill|subagent_type)\\W[{},\d*+?]*\(agent-skills:\)\?(\([^)]*\)|[A-Za-z0-9-]+)")

# Parsed frontmatter: text values, or a list of names for list keys.
Frontmatter = dict


class FrontmatterError(ValueError):
    """Frontmatter that the mini-parser would misread."""


def unquote(value: str) -> str:
    """Strip one pair of matching quotes around a scalar (YAML allows 'x' and "x")."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"" and value[0] not in value[1:-1]:
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> Frontmatter:
    """Parse the YAML subset used here: `key: value`, `key: [a, b]` and `- item` lists, quotes stripped.

    Raises FrontmatterError for what it cannot read faithfully: block scalars (`|`, `>`), values
    continued on indented lines, lines that are not `key: value`, a missing or unterminated block.
    """
    if not text.startswith("---\n"):
        raise FrontmatterError("missing frontmatter: the file must start with '---'")
    end = text.find("\n---", 4)
    if end == -1:
        raise FrontmatterError("unterminated frontmatter: no closing '---'")
    data: Frontmatter = {}
    current_list: str | None = None  # key currently collecting "- item" lines
    for raw in text[4:end].splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # Continuation item of a block list ("  - foo").
        if current_list and line.lstrip().startswith("- "):
            data[current_list].append(unquote(line.lstrip()[2:].strip()))  # type: ignore[union-attr]
            continue
        if line[0] in " \t":
            raise FrontmatterError(f"cannot read indented line '{line.strip()}': keep each value on one line")
        key, sep, value = line.partition(":")
        if not sep:
            raise FrontmatterError(f"cannot read line '{line}': expected 'key: value'")
        current_list = None
        key, value = key.strip(), value.strip()
        if BLOCK_SCALAR.match(value):
            raise FrontmatterError(f"'{key}' uses a YAML block scalar ('{value}'): write the value on one line")
        if key in LIST_KEYS and value.startswith("[") and value.endswith("]"):
            # Inline list: [a, b, c]
            data[key] = [unquote(v.strip()) for v in value[1:-1].split(",") if v.strip()]
        elif value == "":
            # Start of a block list.
            data[key] = []
            current_list = key
        else:
            data[key] = unquote(value)
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
    person = PERSON.search(desc)
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
    for sub in sorted(p for p in (skill_dir / "references").rglob("*") if p.is_dir()):
        errors.append(f"{sub.relative_to(ROOT)}: nested folder in references/ (keep it one level deep)")


def check_reference_toc(skill_dir: Path, errors: list[str]) -> None:
    """N1: reference files over 100 lines open with a `## Contents` heading (partial reads see scope)."""
    for ref in sorted((skill_dir / "references").rglob("*.md")):
        lines = ref.read_text(encoding="utf-8").splitlines()
        near_top = lines[:CONTENTS_WITHIN_LINES]
        if len(lines) > REFERENCE_TOC_THRESHOLD and not any(CONTENTS_HEADING.match(line) for line in near_top):
            errors.append(
                f"{ref.relative_to(ROOT)}: > {REFERENCE_TOC_THRESHOLD} lines without a '## Contents' "
                f"heading in the first {CONTENTS_WITHIN_LINES}"
            )


def check_links(skill_dir: Path, errors: list[str]) -> None:
    """N1: local links resolve, and a reference never links another reference (one level deep)."""
    refs = (skill_dir / "references").resolve()
    for md in sorted(skill_dir.rglob("*.md")):
        in_refs = refs in md.resolve().parents
        for target in LINK_TARGET.findall(CODE.sub("", md.read_text(encoding="utf-8"))):
            if SCHEME.match(target) or target.startswith("/"):
                continue
            # Inside a reference a bare `other.md` is a sibling link too.
            if not (LOCAL_PREFIX.match(target) or (in_refs and target.endswith(".md"))):
                continue
            found = next((p.resolve() for p in (md.parent / target, skill_dir / target) if p.exists()), None)
            if found is None:
                errors.append(f"{md.relative_to(ROOT)}: broken link '{target}'")
            elif in_refs and refs in found.parents and found != md.resolve():
                errors.append(f"{md.relative_to(ROOT)}: links another reference '{target}' (link it from SKILL.md)")


def check_skills(errors: list[str]) -> set[str]:
    """Validate every skill directory and return the set of skill names found."""
    names: set[str] = set()
    for skill_md in sorted(PLUGIN.glob("skills/*/SKILL.md")):
        skill_dir = skill_md.parent
        rel = skill_md.relative_to(ROOT)
        names.add(skill_dir.name)
        text, fm = load_markdown(skill_md, errors)
        if fm is not None:
            if fm.get("name") != skill_dir.name:
                errors.append(f"{rel}: frontmatter name must be '{skill_dir.name}'")
            if not NAME_RE.match(skill_dir.name):
                errors.append(f"{rel}: name must be <= 64 chars of lowercase letters, digits, hyphens")
            check_description(rel, fm.get("description"), errors)
            check_proactive(rel, fm.get("description"), False, errors)
        check_line_budget(rel, text, SKILL_MAX_LINES, errors)
        check_reference_depth(skill_dir, errors)
        check_reference_toc(skill_dir, errors)
        check_links(skill_dir, errors)
    return names


def check_effort(rel: Path, fm: Frontmatter, errors: list[str]) -> None:
    """ADR 0010: every agent declares its effort."""
    if not fm.get("effort"):
        errors.append(f"{rel}: missing 'effort'")


def check_model(rel: Path, fm: Frontmatter, errors: list[str]) -> None:
    """ADR 0010: the model is explicit (cost is a design decision): an alias or a full claude- id."""
    model = fm.get("model")
    if not isinstance(model, str) or not (model in MODEL_ALIASES or FULL_MODEL_ID.match(model)):
        allowed = " | ".join(sorted(MODEL_ALIASES))
        errors.append(f"{rel}: 'model' must be {allowed} or a full claude- id (got {model!r})")


def check_max_turns(rel: Path, name: str, fm: Frontmatter, errors: list[str]) -> None:
    """ADR 0010: workers cap their turns, so a stuck cheap worker cannot burn tokens unseen."""
    turns = fm.get("maxTurns")
    if name in WORKERS and not (isinstance(turns, str) and turns.isdigit() and int(turns) > 0):
        errors.append(f"{rel}: worker must set 'maxTurns' to a positive integer")


def check_read_only(rel: Path, fm: Frontmatter, errors: list[str]) -> None:
    """N7 + ADR 0010: "Read-only" agents block write tools and skip CLAUDE.md in config, not in prompt text."""
    desc = fm.get("description")
    if not isinstance(desc, str) or "Read-only" not in desc:
        return
    unblocked = WRITE_TOOLS - set(as_list(fm.get("disallowedTools")))
    if unblocked:
        errors.append(f"{rel}: Read-only agent must list {', '.join(sorted(unblocked))} in disallowedTools")
    granted = WRITE_TOOLS & set(as_list(fm.get("tools")))
    if granted:
        errors.append(f"{rel}: Read-only agent must not grant {', '.join(sorted(granted))} in tools")
    if not is_true(fm.get("omitClaudeMd")):
        errors.append(f"{rel}: Read-only agent must set omitClaudeMd: true")


def check_workers_exist(agent_names: set[str], errors: list[str]) -> None:
    """ADR 0010: each name in the validator's worker set has an agent file, so the set cannot go stale."""
    for name in sorted(WORKERS - agent_names):
        errors.append(f"{(PLUGIN / 'agents' / f'{name}.md').relative_to(ROOT)}: worker '{name}' has no agent file")


def check_agents(errors: list[str], skill_names: set[str]) -> set[str]:
    """Validate every agent definition, including its preloaded skills; return the agent names found."""
    names: set[str] = set()
    for agent_md in sorted(PLUGIN.glob("agents/*.md")):
        name = agent_md.stem
        rel = agent_md.relative_to(ROOT)
        names.add(name)
        text, fm = load_markdown(agent_md, errors)
        if fm is not None:
            if fm.get("name") != name:
                errors.append(f"{rel}: frontmatter name must be '{name}'")
            if not fm.get("tools"):
                errors.append(f"{rel}: missing 'tools'")
            check_description(rel, fm.get("description"), errors)
            check_proactive(rel, fm.get("description"), name in WORKERS, errors)
            check_effort(rel, fm, errors)
            check_model(rel, fm, errors)
            check_max_turns(rel, name, fm, errors)
            check_read_only(rel, fm, errors)
            for skill in as_list(fm.get("skills")):
                if skill not in skill_names:
                    errors.append(f"{rel}: preloads unknown skill '{skill}'")
        check_line_budget(rel, text, AGENT_MAX_LINES, errors)
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
    for name in sorted(agent_names - WORKERS - named):
        errors.append(f"{(PLUGIN / 'agents' / f'{name}.md').relative_to(ROOT)}: no command names 'agent-skills:{name}'")


def check_offload_rows(errors: list[str]) -> None:
    """N9: every offload worker has a row in commands/offload.md."""
    rel = OFFLOAD_COMMAND.relative_to(ROOT)
    if not OFFLOAD_COMMAND.exists():
        errors.append(f"{rel}: missing")
        return
    text = OFFLOAD_COMMAND.read_text(encoding="utf-8")
    for name in sorted(WORKERS):
        if f"agent-skills:{name}" not in text:
            errors.append(f"{rel}: no row for worker 'agent-skills:{name}'")


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
        for name in sorted(skills - skill_names):
            errors.append(f"{rel}: pattern names unknown skill '{name}'")
        for name in sorted(agents - agent_names):
            errors.append(f"{rel}: pattern names unknown agent '{name}'")
        if grader.relative_to(evals).parts[0] == "no-trigger":
            missing_skills, missing_agents = sorted(skill_names - skills), sorted(agent_names - agents)
            if missing_skills:
                errors.append(f"{rel}: no-trigger pattern misses skill(s) {', '.join(missing_skills)}")
            if missing_agents:
                errors.append(f"{rel}: no-trigger pattern misses agent(s) {', '.join(missing_agents)}")


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
    for number, (x, y) in enumerate(zip(la, lb), 1):
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
            errors.append(f"{rel}: no 'append_system_prompt: |' block (it must embed the offload policy)")
        elif embedded != expected:
            line = first_difference(embedded, expected)
            errors.append(
                f"{rel}: append_system_prompt differs from {POLICY.relative_to(ROOT)} (first difference at line {line})"
            )


def main() -> int:
    errors: list[str] = []
    skills = check_skills(errors)
    agents = check_agents(errors, skills)
    check_commands(errors, skills, agents)
    check_eval_graders(errors, skills, agents)
    check_offload_policy(errors)
    for err in errors:
        print(err)
    print(f"{'FAIL' if errors else 'OK'}: {len(skills)} skills, {len(agents)} agents, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
