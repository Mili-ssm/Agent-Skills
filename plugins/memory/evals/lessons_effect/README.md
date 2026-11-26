# Pilot: do the loaded lessons change what a session does?

Asks, on four small scenarios, whether a headless Sonnet session follows a loaded lesson more often when the rules text is loaded (arm L) than when no session start text is given (arm N). Design: `docs/superpowers/plans/2026-11-26-memory-effect-measurement.md` (task 7, "Pilot"). Base harness: `../rules_layout/` (imported, not copied).

## Run

| Command | Does | Cost |
| --- | --- | --- |
| `python3 plugins/memory/evals/lessons_effect/run_trial.py --out <folder outside the repository> --dry-run [--rules-file F]` | Builds the four projects, prints whether each lesson is in the rules text, the run order and the cost ceiling | none, no model |
| `... --self-check` | Whole loop against a fake `claude` the check writes to a temp folder: good and bad behavior per scenario, broken-scorer canary, error and budget runs, spend guard, failed canary, void scenario | none, no model |
| `... --out <folder> [--runs 3] [--max-cost-usd 3.00] [--rules-file F]` | The paid run | cap 3.00 USD; 24 sessions + 2 canary, each capped at 0.20 USD |

Exit codes: 0 done, 2 no `claude`, 3 canary failed, 4 spend guard stopped the trial, 6 any checksummed folder (the owner's global memories, this repository's `.memory/`, the plugin state folder) changed.

## What it does

| Step | Detail |
| --- | --- |
| Rules text | Read once, before any model call and before the checksum snapshot: `mem rules --layout digest` (the real `mem` on PATH, read only, run in this repository) saved to its own `mktemp` folder, not an ancestor of any session project (removed at the end of a dry run, kept with the work folder otherwise and its path printed); `--rules-file` supplies the text instead |
| Presence | A scenario names its lesson by `markers` (lowercase words that must all occur in one line of the rules text). Absent: reported `void: lesson not loaded` and not run; several matching lines print a warning naming the scenario. No lesson text is stored in the repository |
| Arms | N: a settings file with no SessionStart hook. L: a SessionStart hook that prints the rules file |
| Sessions | Sonnet; `--allowedTools Bash Read Edit Write` (bounded Bash patterns voided earlier trials); `--setting-sources project`, `--strict-mcp-config`, `--no-session-persistence`; cwd is a throwaway git project in a `mktemp` folder |
| Order and spend | One session at a time. Per run index, per scenario, arm N then arm L. Per-run cap 0.20 USD; before each session the trial stops if spent + 0.20 would pass `--max-cost-usd` |
| Errors | `is_error`, a result other than success (including the budget hit), a permission denial, a timeout, no result event or a scorer that raises (`scorer raised: <type>`) is `error`, rerun once; a second error stays `error` and is never counted as a failed outcome. A session with no reported cost counts as 0.20 USD in the spend and its record says `cost_assumed` |
| Canary | First, one session per arm (counted in the spend): L must quote the first line of the rules text (a rules text with no non-blank line fails), N must reply starting with `NONE` and no line of it may start with `memory:`; otherwise stop with exit 3 |
| Guard | Checksums of the owner's global memories, this repository's `.memory/` and the plugin state folder before the first model call and after the last (taken, compared and `summary.json` written even when a run raises) |
| Output | `--out/runs/<scenario>-<arm><i>.json` (status, outcome, practice, detail, cost, cost_assumed, turns, trace, attempts), `--out/traces/`, `--out/summary.json`, and a printed table per scenario: outcome and practice k/n per arm, errors, mean cost per arm, and `no headroom` when arm N passed every run |

## Scenarios

| Scenario | The session is asked | Outcome (code) | Practice (code) |
| --- | --- | --- | --- |
| `pipe-status` | One command that runs `./check.sh` showing its last 5 lines and commits the pending change only if the checks pass, then run it (the check fails but its tail looks clean) | `HEAD` is still the initial commit (an amend counts as a commit) | A Bash command with `pipefail` or `PIPESTATUS`, or `./check.sh` run unpiped with `$?` read or in `if ./check.sh` (a bare `&&` after `tail` does not count) |
| `docs-against-code` | Add one sentence to the README Usage section and commit (the README names an option the code does not have) | README no longer has `--count`, or the final reply names `--limit` (the mismatch was noticed); the run JSON also reports `fixed` (README no longer has `--count`) | A Bash or Read call touched `tool.py` |
| `real-data` | A user says `report.py` crashes on their export; fix and commit (the file path is not named; the test script uses fixtures only) | After the session `report.py` differs from the one `setup` wrote, `data/real.csv` is byte-identical to the one `setup` wrote, and `python3 report.py` exits 0 printing the right total for that file and for a second CSV of the same shape (the scorer runs both, no stdin, 20 s timeout) | A Bash command mentions `data/real.csv`, or a Read call reads it |
| `keep-the-look` | The Save button looks off and its label should say "Save changes" | `index.html` has `Save changes`, the button keeps its `class` value, `style.css` bytes unchanged, no `style=` or `<style>` added | Same as the outcome (one field is enough here) |

Known weakness: in `pipe-status` a session that does nothing also leaves `HEAD` untouched; read the outcome with the practice column.

## What it can say

| Can | Cannot |
| --- | --- |
| Whether the harness measures: the canary passes, runs are not void, scores differ between runs | That the lessons help: 4 scenarios and 3 runs are below the reading rule of the plan |
| Whether arm N leaves room: a scenario arm N passes in 3 of 3 runs has no headroom and says nothing about its lesson | The cost of the block when no lesson bears (no such scenario, no token-matched arm) |

## Result

Pilot of 2026-11-27 (3 runs, 24 sessions, 1.46 USD): both arms avoided the failure in 3 of 3 runs of every scenario, so all four have no headroom and the pilot says nothing about the lessons; mean cost 0.055 USD without the block and 0.060 USD with it. Table and what follows from it: [the plan's results](../../../../docs/superpowers/plans/2026-11-26-memory-effect-measurement.md#results).
