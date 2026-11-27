# Measuring prompt changes

A prompt change is a code change without a type checker: rereading it proves nothing. Measure it.

## Loop

1. Run representative tasks without the change; note the failures (baseline).
2. Write eval cases that capture them: positive triggers, near-miss negatives, the behavior itself.
3. Write the minimum that passes; re-run; compare against the baseline, at least 3 runs per case.
4. Read traces, not only scores: unread reference files are unnecessary or badly signposted; files read every time belong in `SKILL.md`.
5. Re-run with every target model.
6. Record the numbers (ADR or commit message), so the next edit does not undo a measured gain.

## `claude plugin eval` in practice

Learned in this repo (ADRs 0010, 0012, 0013); check `claude plugin eval --help` for the current flags.

| Need | Grader or flag |
|---|---|
| A skill or agent fired | `regex` on `target: trace` matching the `skill` or `subagent_type` field |
| It did not fire | the same `regex` with `match: not_contains`, listing every skill and agent |
| A delegation carried something (a decision, a stop rule) | `tool_used` with `tool: Agent` and `input_match` (regex over the JSON-encoded input; lookaheads for several terms) |
| A file was produced | `file_exists` |
| A judgment on the answer | `llm` with `criteria`; `focus: trace` sees only the first and last 12 messages, so check dispatches with `tool_used` instead |
| Keep traces for re-scoring | `--keep-temp` (traces under `/tmp/claude-eval-*/out/trace.jsonl`) |
| One case | `--case <glob>`: a single glob, no brackets; repeat the command per case |

- Policy text that a case depends on goes into `append_system_prompt`, copied verbatim from its single source, so the case tests the real text.
- Regex graders miss paraphrases ("Do NOT touch"): read failing traces before trusting a 0.

## Codex trace

Use `codex exec --json` in a disposable project and Codex home with the target instructions and roles installed. Save the JSONL output and inspect its tool calls and final answer. Run the same fixtures and scoring rubric against each prompt version and target model, with hooks and role availability held constant. A trace contains prompt and tool output, so keep it private.

Include a delegation case that names the available role and checks the dispatched role, a missing-role case that checks the inline fallback, and an audit case that asks for a review and checks that no project file is changed. Put a unique marker in the injected context and check whether the trace shows it reaching the model before judging the answer. Record configuration, runs, failures, tokens and limits; a shell-hook test proves output, not model delivery. Use seeded disposable data and no live memory store for write checks.
