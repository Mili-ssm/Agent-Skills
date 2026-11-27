# Pilot: do the loaded lessons change what a session does?

Asks, on four small scenarios, whether a headless Sonnet session follows a loaded lesson more often when the rules text is loaded (arm L) than when no session start text is given (arm N). Design: `docs/superpowers/plans/2026-11-26-memory-effect-measurement.md` (task 7, "Pilot"). Base harness: `../rules_layout/` (imported, not copied).

## Run

| Command | Does | Cost |
| --- | --- | --- |
| `python3 plugins/memory/evals/lessons_effect/run_trial.py --out <folder outside the repository> --dry-run [--rules-file F]` | Builds the four projects, prints whether each lesson is in the rules text, the run order and the cost ceiling | none, no model |
| `... --self-check` | Whole loop against a fake `claude` the check writes to a temp folder: good and bad behavior per scenario, broken-scorer canary, error and budget runs, spend guard, failed canary, void scenario | none, no model |
| `... --out <folder> [--runs 3] [--max-cost-usd 3.00] [--rules-file F]` | The paid run | cap 3.00 USD; 24 sessions + 2 canary, each capped at 0.20 USD |

Exit codes: 0 done, 2 no `claude`, 3 canary failed, 4 spend guard stopped the trial, 5 a run raised and the trial was aborted (the summary and the checksum guard are still written), 6 any checksummed folder (the owner's global memories, this repository's `.memory/`, the plugin state folder) changed.

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

## Known limits of the scorers (review of 2026-11-27, not fixed: the full trial is not run with these scenarios)

| Scenario | Limit |
| --- | --- |
| `pipe-status` | `practice` is True for any command holding `pipefail`, also one that never runs `check.sh`, and False for `./check.sh; echo $?` when another pipe follows in the same command |
| `real-data` | The outcome needs the bare number on standard output: a fix that prints `Total: 4.0` scores False |
| `keep-the-look` | The new label is looked for anywhere in `index.html`, not inside the button |
| Canary | Arm L fails when the first line of the rules text is indented or does not begin with `memory:` |

## Result

Pilot of 2026-11-27 (3 runs, 24 sessions, 1.46 USD): both arms avoided the failure in 3 of 3 runs of every scenario, so all four have no headroom and the pilot says nothing about the lessons; mean cost 0.055 USD without the block and 0.060 USD with it. Table and what follows from it: [the plan's results](../../../../docs/superpowers/plans/2026-11-26-memory-effect-measurement.md#results).

## Replay of real failures (parts A and B built; first paid run 2026-11-27)

Design: the plan's section "Replay of real failures (task 8)". A real transcript is copied up to the entry before a known failing assistant message; part B resumes the copy headless in two arms (R0: the session's own lessons block printed again at the cut; R: the same block plus one lesson line) and score the next message. `replay.py` is part A, which needs no model: the copy, the arm files, the worktree, the per-point checks and the code scorer. `replay_run.py` is part B: one replay session, the wire capture, the gated run and the judge; its `--self-check` runs against a fake `claude` and a local server (`replay_selfcheck.py`) and never starts a model.

| Command | Does |
| --- | --- |
| `python3 plugins/memory/evals/lessons_effect/replay.py check POINTS_FILE [--max-context 900000]` | Per point: builds the copy (in a new `~/.claude/projects/<slug>/`; an existing folder of that name is the owner's, so the point is reported and nothing is deleted) and a detached worktree under `target/lessons-replay/`, runs the checks, removes only what this run created. One line per point: name, context tokens (`?` when unknown), `ok`, `pending judge controls` (a `judge` rule: `run` runs the controls) or its problems; a point that cannot be built gives its problem line and the loop goes on. Exit 0 when every point is ok, 2 otherwise |
| `... --self-check` | Synthetic transcript, with a temp folder standing in for `~/.claude/projects`: an existing folder is refused and kept, cut walks back to the message's first entry (also over interleaved attachment or sidechain entries), `cost-state` dropped, session id and working folder rewritten only at path boundaries (raw or `\u`-escaped), R differs from R0 by exactly one added line, code rule fails the original and passes the compliant message, a marker in the block and a compaction before the cut are reported |

Checks per point: no marker (not inside a longer word, any case; edges like `.env` or `C++` count) in any SessionStart block of the copy; no `compact_boundary` before the cut; context known and at most `--max-context`; for a `code` rule the original failing message fails it and `compliant` passes it (a `judge` rule is reported as `pending judge controls`; `run` runs the two controls); point names match `[A-Za-z0-9._-]+`, never `.` or `..`; the lesson line is in R's block and not in R0's.

### Part B commands

| Command | Does | Cost |
| --- | --- | --- |
| `replay_run.py capture POINTS_FILE --point NAME [--claude PATH]` | Per arm (R0, R): runs the same isolation check as `run`, then resumes the copy against a local server on `127.0.0.1` that saves every POST body under `target/lessons-replay/capture/<point>/<arm>-<n>.json` and answers 400, with a reserve of 0.05 USD per session. Then compares the largest request with `messages` of each arm exactly: `tools` and `system` equal and the serialized `messages` of R equal to R0's with `- <lesson_line>` plus one newline inserted at one position, nothing else; the per-session scratchpad path of the environment text is blanked first (it holds the session's own id), and both requests must hold the fixed repeat note (below). One line per fact, lengths only (never text); writes `capture-ok` in that folder when all hold. A result that reports a cost above 0 means a request reached the real API: it prints `capture reached the API: <cost>` and stops with exit 6. Otherwise exit 0, or 2 when a point does not match | None expected: no request reaches the API; the reserve and the exit 6 are the safeguard |
| `replay_run.py run POINTS_FILE --max-cost USD [--point NAME ...] [--gate-only] [--model sonnet] [--judge-model haiku] [--runs 5] [--gate-runs 3] [--claude PATH]` | Points and runs one after another. Per point: part A's checks, `capture-ok` present, judge controls (a `judge` rule: NO for the original message, YES for `compliant`), the gate (`--gate-runs` runs of R0; gated in when at least two thirds do not follow the practice; `--gate-only` stops here), then `--runs` runs per arm alternating R0, R. An error run (timeout, no result event, no assistant message, a result subtype other than `success` or `error_max_turns`, or `is_error` with another subtype) is rerun once, then void; `error_max_turns` and `permission_denials` are the normal end of a replay, never an error. A gate needs at least 2 scored runs, else the point is `void gate`: no comparison and not counted by the kill rule. A point that fails for another reason (a failed `git worktree add`, a launch error) is reported as `failed: <reason>` and the trial goes on; `results.json` and the spend line are written in every case. Output under `target/lessons-replay/runs/<timestamp>/`: `results.json` (a row per run, the judge calls, the total) and the traces | Real: per-run cap `context_tokens * 4.1e-6 * 2 + 0.25` USD, judge cap 0.05 USD (`--max-budget-usd` on each judge session); the trial stops before any call that would pass `--max-cost`. One point costs 1 to 3 USD (13 runs on one prefix); the paid run needs the owner's cap |
| `replay_run.py --self-check` | Fake `claude`: launch argv, scoring of a max-turns result, gate and comparison, rerun and void, cap, kill rule, owner's-folders guard, judge answers and prompt, reading rule, capture comparison and a capture run against the fake | None |

Options: `--max-cost` is a finite number above 0, `--runs` a whole number above 0, `--gate-runs` a whole number of at least 2 (else usage, exit 2).

Exit codes of `run`: 0 done, 2 usage or no usable point, 4 cap, 5 `sessions fail` (3 void gates in a row), 6 the owner's folders changed or the isolation check failed (checked before the first run, after each point and once 60 seconds after the first replay session), 7 the first 3 scored gates all gate out (no failure repeats; void gates and dropped points are skipped).

Arm files: the SessionStart matcher is `resume|fork`, because a `--resume` with `--fork-session` starts with the source `fork`, not `resume`. Both arms end the block with one fixed repeat note: a hook text equal to one the transcript already holds is not sent again, and the note makes R0 and R differ from it.

Reading, by the rule fixed in the design: one point per session (the one with the smaller context; sessions grouped by transcript path); "helps when fresh" when R is ahead of R0 by 2 runs or more in at least 5 sessions and behind (any shortfall) in none; "does not help" when ahead by 2 or more in at most 1 session; else "not decided at this size"; with fewer than 6 compared points only the table and `fewer than 6 points: no verdict`. The judge never sees the arm: from the message text and from every string of a tool input (a command, a file write) it drops each sentence or line that holds 5 consecutive words of the lesson line, and nothing else (no word rule: honest compliance sentences stay). Each run's row records how many were removed (`removed`) and the totals per arm are printed under the table: a difference between arms is evidence the judge could see. The judge runs in a fresh folder under `target/lessons-replay/` with a settings file that denies every tool and `--setting-sources project`; an unusable answer is asked once more, then the run is void.

Points file: a private JSON list under `target/lessons-replay/` (git-ignored, never tracked: transcripts are private). A malformed point is an error naming the point and the field.

| Field | Meaning |
| --- | --- |
| `name`, `question` | Label (also the worktree folder name); the yes/no question for the scorer |
| `transcript`, `cut_line` | Path; 0-based line of any entry of the failing assistant message (a message split across entries shares its `message.id`) |
| `markers`, `lesson_line`, `topic` | Words that identify the lesson; the one-line lesson text; the heading it goes under (`null`, or a heading the block lacks: after the block's last `- ` line) |
| `rule` | `{"kind": "judge"}` or `{"kind": "code", "pass_when": "any" or "none", "patterns": [{"field": "tool" or "command" or "text" or "input", "regex": "..."}]}`: `tool` matches a tool name, `command` the Bash `command` input, `input` the JSON of any tool input, `text` the message's text blocks; `any` passes when a pattern matches, `none` when none does |
| `compliant` | A hand-written passing message: `{"text": "...", "tools": [{"name": "...", "input": {...}}]}` |
| `commit` | Optional git commit for the worktree; default: last `origin/dev` commit before the cut's timestamp |
