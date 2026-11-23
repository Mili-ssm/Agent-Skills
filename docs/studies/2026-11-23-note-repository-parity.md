# Note repository features the memory plugin lacks

Status: proposed · Date: 2026-11-23

The owner's note repository stops receiving studies (owner, 2026-11-23); the `mem` store, which imported all its notes on 2026-11-17, takes over. This lists what the note repository does that the memory plugin (or `agent-skills`) does not yet do, and proposes where each gap would go. Nothing here is built. The checklist was the note repository's own requirements (`I-*`, `C-*`) and its agent contract and research playbook.

## Conclusion

The commands are at parity: every command of the note repository's tool exists in `mem` (same engine), and search quality matches on the same evaluation set (recall@10 0.74 in the store against 0.75 in the note repository, MRR@10 0.48 in both, 216 questions, 2026-11-23). Both sit below C-6's trigger (recall@10 0.8, MRR@10 0.6), so the measured comparison that trigger starts is due in either place (G5). The gaps are the processes around the commands: no commit gate, no research-wave procedure, no writing rules for research notes, and three loops (search misses, stale notes, weekly source watch) that nothing triggers.

---

## Already at parity

| Feature | Note repository | Memory plugin |
|---|---|---|
| Search, read, passages, related, stats, check, index, topics, review, fetch-sources, search-eval, rename, new | its tool | `mem`, same commands |
| Note types, closed schema, topics, filename rule, size limit, reader level (C-1 to C-5, C-10, C-12, C-17) | `check` | `mem check`, same rules |
| Usage log (C-21) | git-ignored file in the repository | the plugin's state folder |
| Sources linked, local copies git-ignored in `.sources/` (I-5, C-14) | rule and `.gitignore` | `.sources/` ignored by the store's git and kept local |
| Agent-facing docs follow vendor guidance (C-11) | the note repository's own docs | the plugin's skills and agents follow Anthropic's authoring guidance as adopted and measured here (ADR 0007, 0014) |
| No business specifics (I-4) | stated, not machine-checked | stronger: forbidden-terms list checked on every global write, and the scope rule in the `memory` skill |
| Sync | git remote | git history plus a private remote since 2026-11-23; pushes are manual until stage 7 |

## Gaps

| # | Feature (source) | Store today | Proposal | Where | Priority |
|---|---|---|---|---|---|
| G1 | Commit gate: `check` on the staged snapshot blocks an invalid commit (C-7, I-6) | `mem history commit` stages with `add -A` and commits without checking; git hooks are disabled on purpose (`core.hooksPath=` in `engine/store_git.py`), so a hook cannot be the gate | Run `mem check` on the changed notes in `store_git._commit`, before staging, which covers `mem history commit`, the automatic commits and `init`; refuse, or commit and flag, on a problem. Matters now that a remote receives the store | memory plugin | high |
| G2 | Research-wave procedure: frame, common brief, parallel writers from full text with local copies, fresh fact-check per area, review of the whole, commit order, lessons (C-18, playbook) | nothing; `mem-research` records short web findings, not literature notes; `mem-synthesize` runs write → fact-check → fix for syntheses only | A skill (or a `mem-synthesize`-like pipeline) for literature and knowledge notes. The 2026-11-23 platform parity study ran this procedure by hand and it caught errors at each step | memory plugin | high |
| G3 | Writing rules for research notes: source ranks, knowledge confidence rubric, `Inference:` labels, conservative level, notes only from a source read (C-9, I-3) | partly: `memory-synthesis` has `Inference:`; `web-research` has source ranks and a confidence scale for answers. Missing are the note-only rules: a single study stays `medium`, `origin: experience`, a note only from a source read, level judged conservatively | A reference file the writing skill and agents load. The owner wants to evaluate these rules first (2026-11-23) | memory plugin, after the owner's evaluation | high |
| G4 | Stale-note review: `llm` knowledge older than 365 days (C-13) and `llm` web literature older than 182 days (C-15) listed for re-reading | `mem review` lists them, but no hook, index line or curation pass runs it | Count the due notes in the curation queue and the `Curation due` line. The 15 vendor-documentation notes of 2026-11-23 come due in May 2027 | memory plugin | medium |
| G5 | Search-quality loop: add a row to the evaluation set on each search miss; a recall or MRR below the trigger starts a measured comparison (C-6, ADR 0009 of the note repository) | `mem search-eval` runs, but no command adds a row and nothing reads the trigger; the store's evaluation file is the imported one | `mem search-eval add "<question>" <note>`; the trigger checked in curation; a line in the `memory` skill on reporting misses | memory plugin | medium |
| G6 | Weekly source watch: a cloud routine proposes new primary sources per domain on a weekly branch, never writing notes (C-16) | set up for the note repository; its current target was not checked | Retarget it to the store's remote, or retire it (owner's choice) | owner, then a routine | medium |
| G7 | Source access routes: which legal route works per source type (open-access indexes first, arXiv HTML for fetch-only readers, sites that block bots) (playbook) | absent | A reference for the `researcher` agent and the `web-research` skill: it helps any web research, not only the store | agent-skills | low |
| G8 | Investigations with their own material on a branch; a `Baseline and contribution` section for experiments (C-19, C-20, I-10) | `mem new research` exists and `check` knows the heading; the store has one branch | Keep investigations with code in the project that runs them (as `docs/studies/` here) and the store for findings. Move the baseline rule into a skill for experiment design | agent-skills (rule); no branch flow | low |
| G9 | Research wave log: one row per wave with what the checks found | the imported log, frozen | Drop the file: record each wave's figures as a lesson with topic `research`, which curation can promote | memory plugin (practice only) | low |
| G10 | Imported repository docs (requirements, decisions, playbook, evaluation set) | copied into the store's `docs/`; 29 of them still name the old tool and paths | Keep the evaluation set (G5); archive the rest, or rewrite the playbook once G2 and G3 settle | memory plugin | low |
| G11 | Adding a topic in the same change as the note that needs it (C-3) | no `mem` command adds a topic; writers would edit `topics.yaml` by hand, against the rule "write only through `mem`" | `mem topics add <id> --parent <id>` | memory plugin | low |
| G12 | The agent contract's lookup options: `--links` for questions that need several notes (measured 89% against 83%), `--also`, `--handles`, `--detail` | the `memory` skill names `--handles` and `--deep` only; `memory-synthesis` already uses `--links` | Add `--links` (and `--detail` for judging hits) to the `memory` skill's search guidance | memory plugin | low |

## Not carried over, on purpose

- The review-dated requirements of the note repository's own tool (its `docs/requirements.md`, under I-9): the memory plugin's requirements live in this repository's `docs/requirements.md`.
- One-file tool run with `uv` (C-8): the plugin ships `bin/mem` and an engine package (ADR 0023).

## Found while checking (outside the gaps)

- `mem note edit` treats a reworded sentence as a dropped one, so a one-phrase fix needs `--shrink` (2026-11-23).
- `mem fetch-sources` needs a store-relative path; an absolute one fails with "not a literature note".
- `mem new` prefixes the slug with year and author, so writers pass only the topic part.
