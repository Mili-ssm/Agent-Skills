# Prompt review fixes (2026-11-26)

Status: done · merged in #195, 2026-11-26

Released on 2026-11-26 · Branch: `fix/prompt-review-2026-11-26` · Base: `dev`

Source: four `prompt-engineer` audits on 2026-11-26 (workers, specialists, skills and commands, memory plugin) and the trigger evals run the same day. The owner asked for the high and medium findings and for the `memory-status-checker` result to be recorded. No `description` changes: every item is a body, a command or injected text, so it ships unmeasured (CLAUDE.md § Rules), except the offload policy, which is measured.

## Tasks

- [x] 1 ADR 0030 `## Review 2026-11-26`: record the trigger results and keep the description. Check: `python3 scripts/validate.py`.
- [x] 2 agent-skills agents: `prompt-engineer` and `ux-reviewer` read CLAUDE.md; data rule in `security-reviewer`, `prompt-engineer`, `consistency-auditor`, `architect`, `pre-mortem`; `check-runner` and `ui-verifier` Bash timeout and `Monitor`; `researcher` word cap and stop rule; `implementer` report file and `none`; `consistency-auditor` rubric file; `architect` output cap. Check: `validate.py`.
- [x] 3 agent-skills skills and commands: `api-design` status-code rows; `feature-briefing` writing-plans guard and intent-elicitation fallback; `ux-design` small-change path; light paths in `architecture-principles` and `intent-elicitation`. Check: `validate.py`.
- [x] 4 memory plugin: `memory-curator` (`--claim` with `--short`, unread short forms, apply report, turn stop); stop rules and the command list in `memory-synthesizer` and `memory-researcher`; `memory-recorder` confirm exception; `memory` skill write threshold; `memory-curation` `--short` bullet. Check: `validate.py`.
- [x] 4b Session start "Curation due" names the agent (`engine/mem.py`, two asserts in `test_curation.py`); `mem.py` made clean first ([plan](2026-11-26-mem-py-ruff-clean.md)).
- [x] 5 Offload policy: name the two-round cap in the `skeptical-reviewer` row and the last line; own commit; `port.py`; measure every `offload-*-with-policy` case and record it in ADR 0017. Check: Eval protocol.
- [x] 6 Changelogs, backlog, `port.py`, `validate.py`, `claude plugin validate .`, review, pull request to `dev`.

## Deferred, with reason

| Finding | Reason |
|---|---|
| `hooks/subagent-start.sh` wording (memory audit 8) | Low confidence, no trace shows the cost; needs a count of `mem search` calls by a trivial subagent first |
| Low findings (about 25) | Out of the owner's request; listed in the session report |
| `ui-verifier` eval (3g) | Owner set it aside on 2026-11-26; browser does not launch in the eval sandbox |
