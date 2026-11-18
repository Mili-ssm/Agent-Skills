# 0012 UI verification worker, worker commands through offload

Status: accepted · Date: 2026-10-29 · Amends 0007, 0011 · Amended by 0017, 0021

## Context

The owner's working agreement requires every web UI change to be verified in a real browser: affected flows, console, desktop and mobile, keyboard and focus, error recovery. That work ran in the main conversation, where screenshots, DOM snapshots and console output fill the most expensive context, or went to `ux-reviewer`, which audits usability and accessibility with Nielsen severities and preloads the whole `ux-principles` skill, most of which a pass/fail check does not use.

A prompt and configuration review of the plugin (2026-10-29) also found that four workers had no command although N8 asked one per agent, and that the owner's offload table, the lever ADR 0010 measured, existed only as escaped strings inside two eval cases.

## Decision

- New worker `ui-verifier` (Sonnet, read-only, `maxTurns`, `omitClaudeMd: true`, no preload). It drives a web UI through the flows and acceptance criteria in its brief at desktop and mobile widths, with whichever Playwright driver is installed (Python, Node or `playwright-cli`), checks console errors and failed requests, and returns pass/fail per check with evidence. Keyboard and error-recovery checks are advisory unless the brief lists them.
- When it starts the app itself, it starts it, runs every flow and stops it in one Bash call, because sandboxed shells may not keep background processes or share the network between calls. It drives only localhost or the brief's URL.
- The "Use proactively" exception of ADR 0010 covers the cheap workers `scripts/validate.py` names, now including `ui-verifier`.
- N8 changes: every specialist agent and the UX design workflow keep a user-only command; workers are forced with `/agent-skills:offload`, which lists each one.
- `ux-principles` names `ui-verifier` for its verification step, as ADR 0010 asks of workflow skills.
- `user-config/offload-policy.md` is the single copy of the offload table. The owner's CLAUDE.md, `cloud-setup.sh` (opt-in) and the eval cases use it verbatim, and `validate.py` checks the cases. This adds `user-config/` to the root layout of ADR 0011: files the owner copies into user scope that are not agents.

## Alternatives

| Option | Rejected because |
|---|---|
| A `verify` mode in `ux-reviewer` | Its preload and Nielsen-severity output do not fit pass/fail checks, and one agent with two contracts blurs both descriptions |
| Playwright MCP tools in the allowlist | Plugin MCP tool names depend on the install (`mcp__plugin_<plugin>_<server>__*`); Bash reaches every driver the owner uses |
| Verification stays in the main conversation | Browser output is the largest context sink the agreement names |
| One command per worker | Five near-identical commands duplicate `/agent-skills:offload` |

## Consequences

- Browser verification runs on Sonnet; the main model reads a bounded report.
- One more agent competes for delegation: ADR 0010 saw `pre-mortem` drop as the catalog grew. ADR 0007's review of 2026-10-29 measures it: no confirmed drop.
- Owners add the `ui-verifier` row to their own offload table.

## Revisit if

`ui-verifier` reports false failures or "not verified" on most runs, or trigger evals show `ux-principles`, `ux-reviewer` or `pre-mortem` losing dispatches to it.

## Measurement 2026-10-29

Offload evals: Sonnet main and 3 runs per case unless noted; `ui-verifier` has 6 runs after its sandbox fix.

| Case | Before | After |
|---|---|---|
| `ui-verifier` with policy: delegated · JS defect · working flow · mobile overflow | `main` has no worker: 0/3 delegated, the main conversation drove the browser itself | 6/6 · 6/6 · 6/6 · 6/6 |
| `check-runner` with policy · without | 3/3 · 0/3 | 3/3 · 2/3 (description unchanged, likely noise) |
| `summarizer` with policy · without | 3/3 · 2/3 | 3/3 · 1/3 (description unchanged, likely noise) |
| `implementer` with policy, Opus main: old row → new row | 0/3 | 3/3 |
| `implementer` with policy, Sonnet main | 0/3 | 0/3 |

- The first `ui-verifier` runs stopped as BLOCKED inside the eval's sandboxed Bash: a global Node Playwright without `NODE_PATH`, no `PLAYWRIGHT_BROWSERS_PATH`, and a read-only `$TMPDIR`. The agent now handles all three.
- The implementer row now names the ~20-line threshold and the review step. A Sonnet main conversation still writes the code itself; delegating to a Sonnet worker would save it nothing.

## Review 2026-11-15

ADR 0021 extends the single copy to `user-config/routing.md`: the owner's user-level file is `offload-policy.md` and `routing.md` verbatim plus personal sections, and the review rows that existed only in that file now live in `routing.md`.

## Review 2026-11-18

`offload-ui-verifier-with-policy` fell from 6/6 on every grader (2026-11-04, ADR 0017) to 2 of 6 runs passing every grader on `main` (ADR 0010 Review 2026-11-18). Two runs kept with `--keep-temp` show the same cause, the machine and not a prompt; the other failing runs are assumed, not shown, to share it:

| Observed in both traces | Detail |
|---|---|
| The worker is dispatched and reports `BLOCKED` | No browser check runs; the main conversation says so and answers from reading `site/`, which the `faq-works` and `mobile-defect` judges fail unless the answer happens to state the result |
| No Playwright library resolves | `import playwright` and `require('playwright')` fail, also with `NODE_PATH="$(npm root -g)"`. The owner's machine now has only the global package `@playwright/cli` (0.1.22); the global `playwright` package this ADR's Measurement relied on is gone |
| `playwright-cli` cannot open a browser in the eval sandbox | It creates `~/.cache/ms-playwright` under the sandbox's home, which is read-only; the installed browsers live in the owner's real home, and setting `PLAYWRIGHT_BROWSERS_PATH` to a new writable directory finds none |

Consequences: the case measures dispatch correctly (6/6) and nothing else until a driver resolves in the sandbox; its judge graders are not evidence about any prompt change meanwhile. Real sessions are not shown to be affected: `ui-verifier` ran 39 times in the week of the study, outside this sandbox.

Options, not decided (owner): install the global `playwright` package again, which restores what the case was measured with; or make `playwright-cli`, which `ui-verifier.md` already names as its third driver, find the browsers of the real home from inside the sandbox (a browsers path in the body or in the case's sandbox), a change that needs its own trace.
