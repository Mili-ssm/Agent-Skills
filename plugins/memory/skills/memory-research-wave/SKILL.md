---
name: memory-research-wave
description: Guides a research wave into the `mem` store - a study that reads several sources or uses several agents, writing literature and knowledge notes from full page text, then fact-checking and fixing them before anyone relies on them. Use when the owner asks to research a subject across several sources or vendors, to study X and record what is found, to survey documentation or papers into notes, or to build notes in parallel with several agents; not for one note or one fact (the `memory` skill alone covers it).
---

# Research wave

> In Codex, use the `memory-*` role when available; if it is absent, do that work inline with `mem`. Claude Code's auto memory is unavailable in Codex. Personal matters are not stored in `mem`.

**Core rule:** cheap agents find leads, shell-equipped writers write notes from the full page text, fresh-context fact-checkers compare every claim with the local copies, and one fixer applies what was verified. Never rely on a note that nobody checked: claims in written notes do carry errors, mostly overstatement (figures in [research-notes.md](../memory/references/research-notes.md)).

The note rules (source ranks, `confidence`, `Inference:`, declarative names, no business specifics) live in [research-notes.md](../memory/references/research-notes.md) of the `memory` skill. Do not restate them here; quote them into each brief (step 2).

## Procedure

1. **Frame and recall.** Write down the question, the areas (one per vendor, paper family or sub-question) and what a finished wave contains. Run `mem search "<subject>"` and `mem find --topic research-practice` and `mem rules --more research`: reuse notes that exist, and learn from past waves before planning.
2. **Common brief plus one dispatch per area.** One shared text, then each area's scope. Quote the rules inline (hard rule on business specifics, source ranks, `Inference:`, declarative names, conservative `confidence` and `level`, the commands of step 4): a subagent cannot be relied on to open a document the brief points to. Say each writer owns only its own notes and may not edit others.
3. **First pass (optional, cheap).** One researcher per area returns leads only: URLs and what each page covers. A fetch summary is never the source of a note (see the figures in [research-notes.md](../memory/references/research-notes.md)).
4. **Writers, in parallel.** One shell-equipped writer per area, each with a disjoint set of notes:
   - fetch the full page text through a shell, read it, record which version you read;
   - `mem new literature ... --body-file <file>` (a knowledge note only for a cross-cutting claim a source states);
   - `mem fetch-sources <store-relative path>` keeps the copy in `.sources/<note>/`;
   - `mem check <paths>` must print nothing.
   Each writer reports the paths it wrote and what it could not fetch.
5. **Fact-check, one fresh context per area.** A checker that did not write the notes compares every claim with the local copies and reports each problem with the note, the claim and the passage that contradicts or fails to support it. Look for overstatement ("only", "cannot", "never"), an absence stated as fact, unlabelled inference, a wrong `level` or `confidence`. It edits nothing.
6. **One fixer.** Apply only verified corrections, with `mem note edit <note> --section <heading> --body-file <file>`; `--shrink` when a sentence is reworded (a reworded sentence counts as dropped). Re-run `mem check`.
7. **Cross-cutting knowledge.** Now write the `knowledge` notes for claims that span areas, each linking its literature notes in `## Evidence`; fact-check them the same way.
8. **Review the whole.** `mem related` on the new notes, `mem stats --orphans`, links between the area notes, `mem check` on the store. Fix what a note misses.
9. **Record the wave.** Figures (notes, claims checked, problem rate by kind, cost, what worked or failed) as one lesson: `mem remember --global --kind lesson --topic research --claim "<the abstract lesson>"`. No client, company or system names.

## Who runs each role

| Role | With the `agent-skills` plugin | Without it |
|---|---|---|
| First-pass researcher | `researcher` | general-purpose subagent, Haiku if the host allows |
| Writer | `implementer` (has a shell) | general-purpose subagent with Bash |
| Fact-checker | `fact-checker` | general-purpose subagent, read-only brief |
| Fixer | `implementer` | general-purpose subagent |

The briefs are the same either way; the writer's brief is what quality depends on.

## Pitfalls

- A writer given only a pointer to the rules ignores them: quote them.
- Two writers sharing a note or a temp file name collide: give each its own notes and its own `mktemp -d`.
- The writer that fact-checks its own notes keeps its misreadings: the checker must be a fresh context.
- A fixer that rewrites a section freely adds new unchecked claims: only verified corrections.
- Skipping step 9 loses the cost and error figures the next wave needs.
