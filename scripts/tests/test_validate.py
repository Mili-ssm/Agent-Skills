"""One negative test per rule of scripts/validate.py: each mutates the mini repo once and expects exactly one error."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import EXTRA_AGENT, SKILL, run_checks

import validate

PLUGIN = "plugins/agent-skills"
SKILL_MD = f"{PLUGIN}/skills/{SKILL}/SKILL.md"
AGENT_MD = f"{PLUGIN}/agents/{EXTRA_AGENT}.md"
WORKER_MD = f"{PLUGIN}/agents/fixer.md"
GRADERS = f"{PLUGIN}/evals"


def edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {rel}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def put(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_mini_repo_is_valid(mini_repo):
    assert run_checks(mini_repo) == []


# --- skills ---------------------------------------------------------------------------------------------------


def test_skill_name_differs_from_folder(mini_repo):
    edit(mini_repo, SKILL_MD, f"name: {SKILL}", "name: other")
    assert run_checks(mini_repo) == [f"{SKILL_MD}: frontmatter name must be '{SKILL}'"]


def test_description_without_trigger(mini_repo):
    edit(mini_repo, SKILL_MD, "Explains the demo. Use when a demo is needed.", "Explains the demo.")
    assert run_checks(mini_repo) == [f"{SKILL_MD}: description must state its trigger ('Use when…')"]


def test_description_first_person(mini_repo):
    edit(mini_repo, SKILL_MD, "Explains the demo.", "Explains what we do.")
    assert run_checks(mini_repo) == [f"{SKILL_MD}: description must be third person (found 'we')"]


def test_quoted_we_passes(mini_repo):
    edit(mini_repo, SKILL_MD, "Explains the demo.", 'Explains the demo for questions such as "what do we know about X".')
    assert run_checks(mini_repo) == []


def test_unquoted_we_fails(mini_repo):
    edit(mini_repo, SKILL_MD, "Explains the demo.", "Explains what do we know about X.")
    assert run_checks(mini_repo) == [f"{SKILL_MD}: description must be third person (found 'we')"]


def test_quoted_phrase_only_is_stripped(mini_repo):
    for desc in (
        '"Explains what we do. Use when asked."',  # whole description quoted
        'Explains "x. Explains what we do. Use when "a" asked.',  # unbalanced quotes
        'Explains "' + "we " * 30 + '". Use when asked.',  # phrase over 60 characters
    ):
        edit(mini_repo, SKILL_MD, "Explains the demo. Use when a demo is needed.", desc)
        errors = run_checks(mini_repo)
        assert f"{SKILL_MD}: description must be third person (found 'we')" in errors, desc
        edit(mini_repo, SKILL_MD, desc, "Explains the demo. Use when a demo is needed.")


def test_curly_quoted_we_passes(mini_repo):
    edit(mini_repo, SKILL_MD, "Explains the demo.", "Explains “what we do”.")
    assert run_checks(mini_repo) == []


def test_description_over_max_length(mini_repo):
    edit(mini_repo, SKILL_MD, "Explains the demo.", "Explains the demo" + " a" * 600 + ".")
    desc = (mini_repo / SKILL_MD).read_text().splitlines()[2].removeprefix("description: ")
    assert run_checks(mini_repo) == [f"{SKILL_MD}: description {len(desc)} chars > 1024"]


def test_description_starts_with_trigger(mini_repo):
    edit(mini_repo, SKILL_MD, "Explains the demo. Use when", "Use when")
    assert run_checks(mini_repo) == [f"{SKILL_MD}: description must say what it does before 'Use when…'"]


def test_skill_says_use_proactively(mini_repo):
    edit(mini_repo, SKILL_MD, "Use when a demo", "Use proactively when a demo")
    assert run_checks(mini_repo) == [f"{SKILL_MD}: only offload workers may say 'Use proactively' (ADR 0010)"]


def test_skill_name_format(mini_repo):
    (mini_repo / PLUGIN / "skills" / SKILL).rename(mini_repo / PLUGIN / "skills" / "Bad_Name")
    edit(mini_repo, f"{PLUGIN}/skills/Bad_Name/SKILL.md", f"name: {SKILL}", "name: Bad_Name")
    edit(mini_repo, "README.md", f"| `{SKILL}` |", "| `Bad_Name` |")
    bad = f"{PLUGIN}/skills/Bad_Name/SKILL.md"
    silent = f"{GRADERS}/no-trigger/neg-demo/graders/silent.md"
    fired = f"{GRADERS}/trigger/{SKILL}/graders/fired.md"
    assert run_checks(mini_repo) == [
        f"{bad}: name must be <= 64 chars of lowercase letters, digits, hyphens",
        f"{silent}: pattern names unknown skill '{SKILL}'",  # the graders still name the renamed skill
        f"{silent}: no-trigger pattern misses skill(s) Bad_Name",
        f"{fired}: pattern names unknown skill '{SKILL}'",
    ]


def test_skill_over_line_budget(mini_repo):
    edit(mini_repo, SKILL_MD, "Body.\n", "Body.\n" + "line\n" * 150)
    lines = len((mini_repo / SKILL_MD).read_text().splitlines())
    assert run_checks(mini_repo) == [f"{SKILL_MD}: {lines} lines > 150"]


def test_reference_nested_folder(mini_repo):
    put(mini_repo, f"{PLUGIN}/skills/{SKILL}/references/deep/inner.md", "Inner.\n")
    assert run_checks(mini_repo) == [f"{PLUGIN}/skills/{SKILL}/references/deep: nested folder in references/ (keep it one level deep)"]


def test_long_reference_without_contents(mini_repo):
    ref = f"{PLUGIN}/skills/{SKILL}/references/long.md"
    put(mini_repo, ref, "# Long\n" + "line\n" * 100)
    assert run_checks(mini_repo) == [f"{ref}: > 100 lines without a '## Contents' heading in the first 15"]


def test_long_reference_with_contents_passes(mini_repo):
    put(mini_repo, f"{PLUGIN}/skills/{SKILL}/references/long.md", "# Long\n\n## Contents\n\n" + "line\n" * 100)
    assert run_checks(mini_repo) == []


def test_broken_relative_link(mini_repo):
    edit(mini_repo, SKILL_MD, "Body.\n", "See [x](references/missing.md).\n")
    assert run_checks(mini_repo) == [f"{SKILL_MD}: broken link 'references/missing.md'"]


def test_reference_links_another_reference(mini_repo):
    base = f"{PLUGIN}/skills/{SKILL}/references"
    put(mini_repo, f"{base}/a.md", "See [b](b.md).\n")
    put(mini_repo, f"{base}/b.md", "B.\n")
    assert run_checks(mini_repo) == [f"{base}/a.md: links another reference 'b.md' (link it from SKILL.md)"]


# --- agents ---------------------------------------------------------------------------------------------------


def test_agent_without_tools(mini_repo):
    edit(mini_repo, AGENT_MD, "tools: [Read, Grep]\n", "")
    assert run_checks(mini_repo) == [f"{AGENT_MD}: missing 'tools'"]


def test_agent_invalid_model(mini_repo):
    edit(mini_repo, AGENT_MD, "model: haiku", "model: gpt")
    edit(mini_repo, "README.md", f"| `{EXTRA_AGENT}` | haiku |", f"| `{EXTRA_AGENT}` | gpt |")
    assert run_checks(mini_repo) == [
        f"{AGENT_MD}: 'model' must be fable | haiku | inherit | opus | sonnet or a full claude- id (got 'gpt')"
    ]


def test_agent_full_model_id_passes(mini_repo):
    edit(mini_repo, AGENT_MD, "model: haiku", "model: claude-haiku-4-5")
    edit(mini_repo, "README.md", f"| `{EXTRA_AGENT}` | haiku |", f"| `{EXTRA_AGENT}` | claude-haiku-4-5 |")
    assert run_checks(mini_repo) == []


def test_agent_missing_effort(mini_repo):
    edit(mini_repo, AGENT_MD, "effort: low\n", "")
    assert run_checks(mini_repo) == [f"{AGENT_MD}: missing 'effort'"]


def test_agent_name_differs_from_file(mini_repo):
    edit(mini_repo, AGENT_MD, f"name: {EXTRA_AGENT}", "name: other")
    assert run_checks(mini_repo) == [f"{AGENT_MD}: frontmatter name must be '{EXTRA_AGENT}'"]


def test_worker_without_max_turns(mini_repo):
    edit(mini_repo, WORKER_MD, "maxTurns: 10\n", "")
    assert run_checks(mini_repo) == [f"{WORKER_MD}: worker must set 'maxTurns' to a positive integer"]


def test_worker_with_zero_max_turns(mini_repo):
    edit(mini_repo, WORKER_MD, "maxTurns: 10", "maxTurns: 0")
    assert run_checks(mini_repo) == [f"{WORKER_MD}: 'maxTurns' must be a positive integer (got '0')"]


def test_agent_effort_outside_allowed_set(mini_repo):
    edit(mini_repo, AGENT_MD, "effort: low", "effort: xhigh")
    assert run_checks(mini_repo) == [f"{AGENT_MD}: 'effort' must be high | low | medium (got 'xhigh')"]


def test_agent_omit_claude_md_not_boolean(mini_repo):
    edit(mini_repo, AGENT_MD, "effort: low", "effort: low\nomitClaudeMd: maybe")
    assert run_checks(mini_repo) == [f"{AGENT_MD}: 'omitClaudeMd' must be true or false"]


def test_check_ports_does_not_repeat_an_error_already_found(mini_repo, monkeypatch):
    line = f"{AGENT_MD}: 'effort' must be high | low | medium (got 'xhigh')"
    fake = subprocess.CompletedProcess([], 1, stdout=f"{line}\nother\n", stderr="")
    monkeypatch.setattr(validate.subprocess, "run", lambda *a, **k: fake)
    errors = [line]
    validate.check_ports(errors)
    assert errors == [line, "other"]


def test_non_worker_says_use_proactively(mini_repo):
    edit(mini_repo, AGENT_MD, "Use when asked for it.", "Use proactively when asked for it.")
    assert run_checks(mini_repo) == [f"{AGENT_MD}: only offload workers may say 'Use proactively' (ADR 0010)"]


def make_read_only(root: Path, tools: str = "[Read, Grep]", omit: bool = True) -> None:
    put(
        root,
        AGENT_MD,
        f"---\nname: {EXTRA_AGENT}\ndescription: Runs the job. Read-only. Use when asked for it.\ntools: {tools}\n"
        f"disallowedTools: [Edit, Write, NotebookEdit]\neffort: low\nmodel: haiku\n"
        + ("omitClaudeMd: true\n" if omit else "")
        + "---\nBody.\n",
    )


def test_read_only_agent_valid(mini_repo):
    make_read_only(mini_repo)
    assert run_checks(mini_repo) == []


def test_read_only_agent_grants_edit(mini_repo):
    make_read_only(mini_repo, tools="[Read, Edit]")
    assert run_checks(mini_repo) == [f"{AGENT_MD}: Read-only agent must not grant Edit in tools"]


def test_read_only_agent_without_disallowed_tools(mini_repo):
    make_read_only(mini_repo)
    edit(mini_repo, AGENT_MD, "disallowedTools: [Edit, Write, NotebookEdit]\n", "disallowedTools: [Edit]\n")
    assert run_checks(mini_repo) == [f"{AGENT_MD}: Read-only agent must list NotebookEdit, Write in disallowedTools"]


def test_read_only_agent_without_omit_claude_md(mini_repo):
    make_read_only(mini_repo, omit=False)
    assert run_checks(mini_repo) == [f"{AGENT_MD}: Read-only agent must set omitClaudeMd: true"]


def test_agent_preloads_unknown_skill(mini_repo):
    edit(mini_repo, AGENT_MD, "model: haiku\n", "model: haiku\nskills: [ghost]\n")
    edit(mini_repo, "README.md", f"| `{EXTRA_AGENT}` | haiku | — |", f"| `{EXTRA_AGENT}` | haiku | ghost |")
    assert run_checks(mini_repo) == [f"{AGENT_MD}: preloads unknown skill 'ghost'"]


def test_agent_over_line_budget(mini_repo):
    edit(mini_repo, AGENT_MD, "Body.\n", "Body.\n" + "line\n" * 120)
    lines = len((mini_repo / AGENT_MD).read_text().splitlines())
    assert run_checks(mini_repo) == [f"{AGENT_MD}: {lines} lines > 120"]


def test_worker_agent_file_missing(mini_repo):
    (mini_repo / WORKER_MD).unlink()
    assert run_checks(mini_repo) == [
        f"{WORKER_MD}: worker 'fixer' has no agent file",
        f"{PLUGIN}/commands/offload.md: references unknown agent/skill 'fixer'",
        f"{GRADERS}/no-trigger/neg-demo/graders/silent.md: pattern names unknown agent 'fixer'",
        "README.md: Agents table has extra row 'fixer' (no such item in the plugin)",
    ]


# --- commands -------------------------------------------------------------------------------------------------


def test_command_without_arguments(mini_repo):
    cmd = f"{PLUGIN}/commands/{EXTRA_AGENT}.md"
    edit(mini_repo, cmd, " $ARGUMENTS", "")
    assert run_checks(mini_repo) == [f"{cmd}: body must use $ARGUMENTS"]


def test_command_without_description(mini_repo):
    cmd = f"{PLUGIN}/commands/{EXTRA_AGENT}.md"
    edit(mini_repo, cmd, "description: A command.\n", "")
    assert run_checks(mini_repo) == [f"{cmd}: missing 'description'"]


def test_command_without_argument_hint(mini_repo):
    cmd = f"{PLUGIN}/commands/{EXTRA_AGENT}.md"
    edit(mini_repo, cmd, 'argument-hint: "[task]"\n', "")
    assert run_checks(mini_repo) == [f"{cmd}: missing 'argument-hint'"]


def test_command_model_invocable(mini_repo):
    cmd = f"{PLUGIN}/commands/{EXTRA_AGENT}.md"
    edit(mini_repo, cmd, "disable-model-invocation: true", "disable-model-invocation: false")
    assert run_checks(mini_repo) == [f"{cmd}: commands must set disable-model-invocation: true (user-only)"]


def test_non_worker_agent_without_command(mini_repo):
    cmd = f"{PLUGIN}/commands/{EXTRA_AGENT}.md"
    edit(mini_repo, cmd, f"agent-skills:{EXTRA_AGENT}", "agent-skills:" + SKILL)
    assert run_checks(mini_repo) == [f"{AGENT_MD}: no command names 'agent-skills:{EXTRA_AGENT}'"]


def test_command_names_unknown_agent(mini_repo):
    cmd = f"{PLUGIN}/commands/{EXTRA_AGENT}.md"
    edit(mini_repo, cmd, "Run ", "Run agent-skills:ghost and ")
    assert run_checks(mini_repo) == [f"{cmd}: references unknown agent/skill 'ghost'"]


def test_offload_command_misses_worker_row(mini_repo):
    cmd = f"{PLUGIN}/commands/offload.md"
    edit(mini_repo, cmd, "| agent-skills:fixer |", "")
    assert run_checks(mini_repo) == [f"{cmd}: no row for worker 'agent-skills:fixer'"]


# --- eval graders and offload policy --------------------------------------------------------------------------


def test_trigger_grader_names_unknown_agent(mini_repo):
    grader = f"{GRADERS}/trigger/{SKILL}/graders/fired.md"
    # a trigger grader through subagent_type: same function, agent group
    put(mini_repo, grader, "---\ntype: regex\npattern: 'subagent_type\\W{1,8}(agent-skills:)?ghost\\b'\n---\n")
    assert run_checks(mini_repo) == [f"{grader}: pattern names unknown agent 'ghost'"]


def test_trigger_grader_names_unknown_skill(mini_repo):
    grader = f"{GRADERS}/trigger/{SKILL}/graders/fired.md"
    edit(mini_repo, grader, SKILL, "ghost")
    assert run_checks(mini_repo) == [f"{grader}: pattern names unknown skill 'ghost'"]


def test_no_trigger_grader_misses_agent(mini_repo):
    grader = f"{GRADERS}/no-trigger/neg-demo/graders/silent.md"
    edit(mini_repo, grader, f"|{EXTRA_AGENT}", "")
    assert run_checks(mini_repo) == [f"{grader}: no-trigger pattern misses agent(s) {EXTRA_AGENT}"]


def test_no_trigger_grader_misses_skill(mini_repo):
    grader = f"{GRADERS}/no-trigger/neg-demo/graders/silent.md"
    edit(mini_repo, grader, f"({SKILL})", "(other-skill)")
    errors = run_checks(mini_repo)
    assert errors == [
        f"{grader}: pattern names unknown skill 'other-skill'",
        f"{grader}: no-trigger pattern misses skill(s) {SKILL}",
    ]


def test_policy_embed_differs(mini_repo):
    case = f"{GRADERS}/offload/summarizer-with-policy/case.yaml"
    edit(mini_repo, "user-config/offload-policy.md", "x", "changed")
    assert run_checks(mini_repo) == [
        f"{case}: append_system_prompt differs from user-config/offload-policy.md (first difference at line 1)"
    ]


def test_policy_embed_missing_block(mini_repo):
    case = f"{GRADERS}/offload/summarizer-with-policy/case.yaml"
    put(mini_repo, case, "name: x\n")
    assert run_checks(mini_repo) == [f"{case}: no 'append_system_prompt: |' block (it must embed the offload policy)"]


def test_policy_file_missing(mini_repo):
    (mini_repo / "user-config" / "offload-policy.md").unlink()
    assert run_checks(mini_repo) == [
        "user-config/offload-policy.md: missing (offload with-policy evals embed it)",
        "user-config/offload-policy.md: public path is missing (ADR 0026)",
    ]


# --- README catalog -------------------------------------------------------------------------------------------


def test_readme_catalog_missing_agent(mini_repo):
    edit(mini_repo, "README.md", f"| `{EXTRA_AGENT}` | haiku | — | does it |\n", "")
    assert run_checks(mini_repo) == [f"README.md: Agents table is missing a row for '{EXTRA_AGENT}'"]


def test_readme_catalog_extra_skill(mini_repo):
    edit(mini_repo, "README.md", f"| `{SKILL}` | does it |", f"| `{SKILL}` | does it |\n| `ghost` | does it |")
    assert run_checks(mini_repo) == ["README.md: Skills table has extra row 'ghost' (no such item in the plugin)"]


def test_readme_catalog_wrong_model(mini_repo):
    edit(mini_repo, "README.md", f"| `{EXTRA_AGENT}` | haiku |", f"| `{EXTRA_AGENT}` | opus |")
    assert run_checks(mini_repo) == [
        f"README.md: Agents table: '{EXTRA_AGENT}' has model 'opus', frontmatter says 'haiku'"
    ]


def test_readme_catalog_wrong_preloads(mini_repo):
    edit(mini_repo, "README.md", f"| `{EXTRA_AGENT}` | haiku | — |", f"| `{EXTRA_AGENT}` | haiku | {SKILL} |")
    assert run_checks(mini_repo) == [
        f"README.md: Agents table: '{EXTRA_AGENT}' preloads ['{SKILL}'], frontmatter says []"
    ]


def test_readme_catalog_missing_command(mini_repo):
    edit(mini_repo, "README.md", f"| `/agent-skills:{EXTRA_AGENT}` | does it |\n", "")
    assert run_checks(mini_repo) == [f"README.md: Commands table is missing a row for '{EXTRA_AGENT}'"]


# --- public paths and versions --------------------------------------------------------------------------------


def test_public_path_missing(mini_repo):
    (mini_repo / "LICENSE").unlink()
    assert run_checks(mini_repo) == ["LICENSE: public path is missing (ADR 0026)"]


def test_catalog_source_path_missing(mini_repo):
    (mini_repo / PLUGIN / ".claude-plugin" / "plugin.json").unlink()
    errors = run_checks(mini_repo)
    assert f"{PLUGIN}/.claude-plugin/plugin.json: missing or not valid JSON" in errors


def test_readme_anchor_missing(mini_repo):
    edit(mini_repo, "README.md", "## Update\n\n", "")
    assert run_checks(mini_repo) == ["README.md: missing heading '## Update' (ADR 0026)"]


def test_version_without_changelog_entry(mini_repo):
    edit(mini_repo, f"{PLUGIN}/.claude-plugin/plugin.json", "1.0.0", "1.1.0")
    assert run_checks(mini_repo) == [f"{PLUGIN}/CHANGELOG.md: no heading '## [1.1.0] - YYYY-MM-DD' (ADR 0027)"]


def test_version_not_semver(mini_repo):
    edit(mini_repo, f"{PLUGIN}/.claude-plugin/plugin.json", "1.0.0", "1.0")
    assert run_checks(mini_repo) == [f"{PLUGIN}/.claude-plugin/plugin.json: 'version' is '1.0', expected SemVer X.Y.Z (ADR 0027)"]


def test_changelog_missing(mini_repo):
    (mini_repo / PLUGIN / "CHANGELOG.md").unlink()
    assert run_checks(mini_repo) == [f"{PLUGIN}/CHANGELOG.md: missing (ADR 0027)"]


def test_marketplace_entry_carries_version(mini_repo):
    rel = ".claude-plugin/marketplace.json"
    put(mini_repo, rel, json.dumps({"plugins": [{"name": "agent-skills", "source": "./plugins/agent-skills", "version": "1.0.0"}]}))
    assert run_checks(mini_repo) == [
        f"{rel}: entry 'agent-skills' carries 'version'; plugin.json is the only source (ADR 0027)"
    ]


# --- frontmatter, version_key, block_scalar -------------------------------------------------------------------


def test_parse_frontmatter_values():
    fm = validate.parse_frontmatter(
        "---\nname: x\ndescription: 'quoted: value'\ntools: [Read, \"Grep\"]\nskills:\n  - a\n  - b\nargument-hint: [x]\n---\nbody\n"
    )
    assert fm == {
        "name": "x",
        "description": "quoted: value",
        "tools": ["Read", "Grep"],
        "skills": ["a", "b"],
        "argument-hint": "[x]",
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("name: x\n", "missing frontmatter"),
        ("---\nname: x\n", "unterminated frontmatter"),
        ("---\ndescription: |\n  text\n---\n", "uses a YAML block scalar"),
        ("---\ndescription: a\n  continued\n---\n", "cannot read indented line"),
        ("---\njust text\n---\n", "expected 'key: value'"),
    ],
)
def test_parse_frontmatter_malformed(text, message):
    with pytest.raises(validate.FrontmatterError, match=message):
        validate.parse_frontmatter(text)


def test_version_key_orders_versions():
    key = validate.version_key
    assert key("1.10.0") > key("1.9.0")
    assert key("1.0.0-rc.1") < key("1.0.0")
    assert key("1.0.0-alpha") < key("1.0.0-beta")


def test_block_scalar_decodes_literal_block():
    text = "a:\n  key: |\n    one\n\n    two\n  other: x\n"
    assert validate.block_scalar(text, "key") == "one\n\ntwo"
    assert validate.block_scalar(text, "absent") is None
