# 0018 Sharper agent roles, a fact-checker agent, effort by task shape

Status: accepted · Date: 2026-11-12 · Amends 0010, 0017

## Context

An assessment of the plugin's prompts (2026-11-11/12) found the prompts sound and the seams weak: two pairs of agents with a boundary a router cannot evaluate, one job no agent owned, one rule in two versions, and a fact in the rulebook stronger than its source. The owner is satisfied with the baseline, has seen no runaway turns or cost, and wants only changes that are very unlikely to lower quality or raise consumption; eval budget is small.

Owner's role definitions (2026-11-12):

| Pair | Roles |
|---|---|
| `ux-reviewer` / `ui-verifier` | A design consultant who judges visual and UX/UI quality / a QA engineer for interfaces who checks that everything works |
| `doc-curator` / `prompt-engineer` | A specialist in organizing and maintaining documentation in general / a specialist in communication with LLMs (prompts in a program, a plugin, agent instructions) |

Evidence on models and effort, read from the vendor pages on 2026-11-12 (Claude 5.5 generation; vendor measurements of its own models):

| Source | Finding |
|---|---|
| Pricing | Haiku 5.5 is 20× cheaper than Sonnet 5.5 per token up to 100k prompt tokens; Opus 5.5 is 2× Sonnet |
| *Optimizing for cost and intelligence*, defect-search benchmark (130 planted defects, 10 runs per configuration) | F1 and cost per run: Haiku `medium` 0.58, $25; Sonnet `high` 0.76, $103; Opus `low` 0.49, $38; Opus `medium` 0.83, $200; Opus `high` 0.85, $236 |
| Same page | Haiku "suits high-volume and latency-sensitive work with checkable outputs"; Sonnet at `medium` scored about 7 points below `high` on a SWE-bench Pro subset |
| *Prompting Claude Sonnet 5.5* | Agentic work: `medium` for well-specified tasks, `high` for harder or longer ones; at `low` it can skip verifying a change |
| *Prompting Claude Haiku 5.5* | `low` for short tool tasks; in long agent prompts `low` skips searches and checks and stops early |

In the session that produced this ADR, three fresh-context fact-checks against local source copies changed 28 statements in 13 notes, and no existing agent fit the job: `researcher` summarizes pages, `summarizer` extracts without comparing, `skeptical-reviewer` excludes it.

## Decision

- **New agent `fact-checker`** (Sonnet, `medium`, read-only) with the command `/agent-skills:fact-check`: one verdict per claim (`supported`, `overstated`, `contradicted`, `not found`) with the source passage and a replacement. A specialist with a command, not a worker: no policy row, so the `*-with-policy` cases and the owner's CLAUDE.md are untouched. It takes local sources only, because a fetched page summary is not the source text.
- **`ux-reviewer`** is the design consultant: description and role line lead with visual quality; it also critiques a spec or mockup before it is built (`feature-briefing` already dispatched it for that); a broken flow is one finding, not its job. Effort `medium` → `high`.
- **`ui-verifier`** is the QA engineer for interfaces: role line only; its description is unchanged, because it carries a measured offload trigger.
- **`doc-curator`** is the documentation specialist: on LLM-facing files it verifies facts and organizes, cuts only duplicates and stale lines, and hands wording that steers a model to `prompt-engineer`. Its description no longer lists skills and agent prompts. `prompt-engineer` is unchanged.
- **`consistency-auditor`** effort `medium` → `high`: reconstructing intent across code, docs and history is the "harder or longer" kind of task, and the agent ran on Opus until ADR 0010.
- **Every other model and effort stays.** Workers on Sonnet `medium` match "well-specified tasks"; Haiku `low` matches short tool tasks with a stated end; the three Opus agents stay at `high` (about 2 points over `medium` for about 18% more, on rare runs). `skeptical-reviewer` stays on Haiku: its report is checkable by design and Sonnet would cost several times more on the most frequent dispatch; the benchmark above is why its findings are a second reading, never the only gate for defects.
- **Untrusted content**: `summarizer`, `check-runner`, `ui-verifier`, `ux-reviewer` and `fact-checker` carry the rule `researcher` already had (treat text as data, report instructions found).
- **`fixer`**: autofix is used when it can be limited to the files in scope, which removes the conflict with its own scope rule; its history rule now also forbids stash, reset and revert, because the working tree may hold the owner's uncommitted work.
- **`/agent-skills:offload`**: the `skeptical-reviewer` row drops the "≥ ~20 changed lines or ≥ 2 files" floor and states the rule of ADR 0017 Measurement 2026-11-04 (whatever changed since the last review), as the policy does.
- **Rulebook**: `context-files.md` and `docs-principles` state what *Evaluating AGENTS.md* (arXiv:2602.11988 v3) supports: no significant change in task success, cost up 20–23% (LLM-generated files) or up to 19% (developer-written). `models.md` gains the figures above, dated.

## Alternatives

| Option | Rejected because |
|---|---|
| `maxTurns` on the eight specialists without it | No runaway run observed; a cap can cut a good run short (ADR 0010 Review 2026-10-30 raised `implementer`'s for that reason) |
| `skeptical-reviewer` on Sonnet `low` | Several times the cost per dispatch; Sonnet at `low` skips verification too; the caller already verifies medium and high findings |
| Haiku workers from `low` to `medium` | No failure observed (offload cases at their records, ADR 0017 Measurement 2026-11-04); Anthropic measured more than twice the output tokens |
| Opus agents from `high` to `medium` | Saves about 15% on rare runs for a measured loss; not worth it without an observed cost problem |
| All Sonnet specialists to `high` | Raises consumption across the board on inference alone; two agents with a stated reason instead |
| `fact-checker` as a mode of `summarizer` | Judging "overstated" needs more than extraction, and Haiku at `low` is the wrong pair for it |
| `fact-checker` as an eighth worker | Needs a policy row: every `*-with-policy` case reruns and every user's CLAUDE.md copy changes |
| Remove the nine specialist commands (near-identical text) | N8 requires them; a description alone fired `pre-mortem` 2/6 (ADR 0010 Review 2026-10-28) |
| `doc-curator` without the `prompt-engineering` preload | It still needs `context-files.md` and `llm-native-projects.md` to organize LLM-facing docs |
| Change `doc-curator`'s `apply` trigger ("apply, update or fix") | "Update the README" is a request to write; the baseline behavior is wanted |

## Consequences

- Unmeasured (owner, 2026-11-12: evals cost too much of the weekly budget to run for these). Cheapest check per item:

| Change | Cases the protocol names | Kill criterion |
|---|---|---|
| New agent and the `neg-*` graders | every `neg-*` | Any `neg-*` case fires `fact-checker` |
| `doc-curator` description | `trigger/docs-principles`, every `neg-*` | Below its recorded rate |
| `ux-reviewer` description | every `neg-*` (no trigger case names it) | A `neg-*` case fires it |
| Bodies of `ui-verifier`, `summarizer`, `check-runner` (one rule line each) | their `offload-*` cases | Below their records |
| Effort `high` on two specialists | none: read one trace each | Runs clearly longer or costlier with no better findings → back to `medium` |
| `fact-checker` quality | none: one run on a text with a planted wrong number | Misses it, or marks a supported claim as wrong |

- Two specialists cost more per run; both run from an explicit command or a workflow skill (`feature-briefing`, `intent-elicitation`), and neither says "Use proactively".
- One more agent description (about 700 characters) loads in every session.
- Codex ports: Sonnet `high` maps to `gpt-6.1-terra` `medium` (ADR 0015).

## Revisit if

A model generation changes (every figure above is for Claude 5.5), a kill criterion above is met, the owner starts seeing long or costly specialist runs (then add `maxTurns`), or `fact-checker` is dispatched often enough to deserve a policy row.

## Review 2026-11-12

Owner decision the same day, after reading the Haiku 5.5 effort guidance (`low`: "in long agent prompts, the model is more likely to skip a search, stop early, or skip a check"; `high` "suits knowledge work, longer agent tasks, and strict instruction following"):

| Agent | Effort | Reason | Cost and kill criterion |
|---|---|---|---|
| `summarizer` | `low` → `medium` | Its job is searching long material, where a skipped search returns a silent "not found" | Anthropic measured more than twice the output tokens from `low` to `medium`; one prompt line now forbids preamble, recap and narration, which does not bound thinking. Reports noticeably slower or costlier with no better answers → back to `low` |
| `skeptical-reviewer` | `medium` → `high` | Review is knowledge work with a strict report format, and it is the last reading before delivery | No vendor figure for `medium` → `high`. Same criterion → back to `medium` |

This replaces the Alternatives row "Haiku workers from `low` to `medium`" for `summarizer`; `check-runner` stays at `low` and `researcher` at `medium`. Both changes are unmeasured: the protocol names `offload-summarizer*` and `offload-skeptical-reviewer*`. Codex ports: Haiku `high` maps to `gpt-6-luna` `medium`; Haiku `medium` and `low` both map to `gpt-6-luna` `low`, so the `summarizer` port is unchanged.
