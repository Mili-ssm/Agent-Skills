# Changelog

All notable changes to this plugin. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/).

## [Unreleased]

### Added

- On Codex, plugin options are read from one file per option under `~/.config/agent-memory/` (first line; `$XDG_CONFIG_HOME` honoured), because Codex sets no plugin option variables; a set variable wins (ADR 0038).
- The five `memory-*` subagents are generated as Codex roles (`ports/codex/memory/agents/*.toml`, from `scripts/port.py`); copy them to `~/.codex/agents/` (README, Codex step 5). The synthesizer finds its skill in Codex's plugin cache there (ADR 0038).

## [0.18.0] - 2026-11-27

### Added

- Experimental Codex runner for the background passes settle and corroborate (including the automatic fill): they run on `codex exec` in a sandboxed run folder when the runner is `codex`, with a per-run token cap (`MEM_CODEX_TOKENS`, default 500000) in place of a USD budget, and record `tokens` and `runner` in their status and logs. On Codex, settle adds a rule to its brief (a pair where one claim states anything the other lacks is never a `merge`), because Codex reads the brief literally; corroborate is not yet tried on real Codex. Synthesis, the curator, research, capture and integrate refuse `codex` and run on Claude only (integrate: Codex appended almost none of 17 in the 2026-11-27 trial). Choose the runner with `--runner` on the pass command, the environment variable `MEM_RUNNER`, the config file `~/.config/agent-memory/runner` (first line) or the plugin option `runner`, highest first; empty means `claude`. A `codex` default is ignored, with one line on stderr, by the passes that stay on Claude; an explicit `--runner codex` on them exits 2.

### Fixed

- `mem install-command`: the launcher reads a plugin-root record with Windows line endings, and Codex now suggests `<plugin root>/bin/mem install-command` whenever no `mem` resolves on `PATH` (also when the launcher sits in a folder off `PATH`).

### Changed

- Codex setup in the README: the VS Code extension never asks to trust hooks, so trust them once from the CLI's `/hooks` screen. Note for 0.17.0: Claude Code sessions also record the plugin root at session start (`~/.local/state/agent-memory/plugin-root`), which the `mem` launcher reads.

## [0.17.0] - 2026-11-27

### Added

- Codex can load the plugin from the same folder (`.codex-plugin/`): it opens sessions with the memory index and gives subagents the memory line, without the Claude-only parts (auto memory, `memory:*` subagents). Setup (marketplace, hook trust, the sandbox's `writable_roots`): README § Codex. The shared hook scripts `session-index.sh` and `subagent-start.sh` gain Codex branches (selected by `MEM_HOST=codex`); Claude Code output is unchanged, and the `session-index` hook log gains a `host` field.
- `mem install-command` puts a `mem` launcher in `~/.local/bin` (or `--bin-dir`), so Claude, Codex and your terminal all call plain `mem`; it follows the plugin copy the last session recorded, survives plugin updates, and `--remove` deletes it. It never overwrites a `mem` it did not write.

## [0.16.1] - 2026-11-27

### Fixed

- `mem-integrate run` now adds new sentences to syntheses. In 0.16.0 its check session rejected almost every note meant to add a sentence ("the part does not mention this yet"), so a run placed only references on existing sentences. Measured on 2026-11-27: on fixed test rows, 99 of 102 right additions accepted and none of 120 wrong rows (not on the topic, wrong part, contradicting the part, wrong sentence), against 24 of 136 before; the seeded trial placed 8 new sentences, all backed by their notes (checked by a second model), with no wrong placement; on a copy of a real store, none of 32 deliberately wrong placements was accepted in two runs (a third run could not read its oversized input). Kill criteria: [plan](https://github.com/Mili-ssm/Agent-Skills/blob/main/docs/superpowers/plans/2026-11-27-memory-integrate-check-append.md).
- `mem-integrate run`: a check answer with a stray row-shaped line (a `row:` label, a cut line) no longer discards the whole synthesis for that run; only rows the place session proposed can be kept, ignored lines are logged, and an answer with a prose or `#` line (such as a "Rejected:" heading) applies nothing.

## [0.16.0] - 2026-11-27

### Added

- `mem synthesis integrate FILE` joins loose knowledge notes to parts of a synthesis from a file of `note | s:<handle>#<section> | append|unit N | fingerprint` lines: `append` adds the note's claim as a new paragraph at the end of the part, before its `Sources:` line, with its reference; `unit N` only references the note on an existing sentence. A row is refused when the note is already part of a synthesis, superseded, disputed or not a knowledge note, when its claim holds a secret or a forbidden term, or when the part changed since it was read. All rows of a file are written as one logged group: undo it with `mem restore s:<handle>` while it is the newest change of the synthesis. A rows file is undone as a whole, so rows for two syntheses in one file are undone together; one file per synthesis keeps them apart. `mem synthesis integrate --candidates` prints as JSON the notes each synthesis could take, with its parts and their units.
- `mem-integrate run [--store PATH] [--claude PATH] [--budget USD] [--dry-run]` joins loose knowledge notes to the parts of syntheses. Per synthesis, one cheap read-only session proposes where each note goes and a second one checks the proposal; only rows both agree on are applied with `mem synthesis integrate`, one logged group per synthesis (undo a run with `mem-integrate --undo RUN`, which checks the log before each restore and verifies its output after it; a single hand-run `mem synthesis integrate` is undone with `mem restore s:<handle>` while it is the newest change of that synthesis). It takes the `mem-auto` run lock, commits the store before and after, and never starts by itself: you opt in by running it. Default budget 0.50 USD per run (`--budget` must be a finite number above 0, otherwise exit 2); `--dry-run` lists what would run and starts nothing. Notes it has handled are skipped until they change; state lives in the plugin state folder under `integrate/`. `mem-integrate --self-check` proves the briefs, the answer parser and the whole flow against a fake `claude` at no cost; a session that says it could not read its input file is recorded as a failure and applies nothing. `mem-integrate --undo RUN` undoes a run's groups newest first, and only while each is still the newest change of every file it wrote; it stops at the first refused group (exit 2, names the file, restores nothing for that group) and running it again continues after you fix the file. `mem-integrate status` prints the last run: id, state, cost, groups and failure lines. One trial on a test synthesis (2026-11-27): no note was placed where it does not belong and `--undo` restored every file, but none of the 17 notes that should have added a sentence did; it placed only references on existing sentences (8). Expect few new sentences until this is investigated.
- `mem curate --new-since` no longer counts a file whose last change was an integration (`mem synthesis integrate`), or an integration that was undone (`mem-integrate --undo`), so an integration run and its undo do not make its notes look new.

### Changed

- Settling (`mem-settle`, option `auto_settle`) now also finds a duplicate global memory written in other words: it compares a new memory with existing ones that share fewer words than before, and it can join two wordings of one fact that differ in a negation ("does not keep" against "drops") by superseding the older record. Expect more pairs in `mem settle pending`, more settlings in the session start line, and a model session in more runs (about 0.015 USD each); every settling is undone with `mem settle undo`. The curation queue you read is unchanged. A record that came from the web or from a pipeline is never the one kept.
- The background passes (`mem-auto`, `mem-capture`, `mem-corroborate`, `mem-research`, `mem-settle`, `mem-synthesize`) now run through `uv`, like `mem`: no system `python3` is needed, but `uv` is required. A missing `uv` is reported once in the session start text. Migration: install `uv` (https://docs.astral.sh/uv/) if you have not; after a plugin update on an offline machine the first run fails until you are online once.
- Capture, settle, synthesis and curation (`mem-auto`) sessions no longer load MCP servers (`--strict-mcp-config`), like the corroborate, research and reference sessions already did; capture sessions have only the Read and Write tools. Impact: these background sessions cannot call tools from your MCP servers; none of the plugin's prompts asks them to. Migration: none.
- Every entry point now finds the store the same way: `--root`, then `MEM_STORE`, then the first line of the `store` config file, then the default store. Background commands and `mem-research`/`mem-synthesize` use the store named in the config file when `MEM_STORE` is unset, as `mem` already did.
- The default store counts only when it holds its `mem-store.yaml` marker. A folder there without the marker is no longer used (`mem` says it is not used and how to adopt it: add the file by hand only if you own that folder and mean to write to it).
- With no `HOME` and no `XDG_DATA_HOME`, no entry point uses a default store (`mem-research` and `mem-synthesize` no longer fall back to the home folder from the system user database).
- The config files under `~/.config/agent-memory/` (`store`, `memories`) can be edited by hand. The session start hook records what it writes in `<name>.hook` next to the file, and no longer deletes or overwrites a file it did not write. With no `store` option, the hooks hand over the store the `store` file names, else the default store. Migration: a file written by an older version has no record and is kept, so after changing or clearing the `store` option, check that `~/.config/agent-memory/store` names the store you want, or delete it.

### Fixed

- The background curator of `mem-auto` can now list the short forms nobody read (`mem rules --unread`); before, that command was not among the ones its session may run, so the queue item "short forms nobody read" was never processed in the background. It still cannot mark them as read.
- A background session stopped by its time limit in the middle of a multibyte character no longer loses its partial output with a decoding error.
- The compaction handoff check reports a missing plan file with a very long name on Python 3.12 and 3.13, as it already did on 3.14.
- Research checks keep the page text after an unclosed `<script>` or `<style>` on early Python 3.12 patches (3.12.0), as later patches do.
- Research checks refuse a verdict whose quote is not text instead of stopping with an error.

## [0.15.0] - 2026-11-26

### Added

- The memory offload table (about 520 tokens, estimated at 4 bytes per token) now loads from a second `SessionStart` hook at session start, after `/clear` and after a compaction, so you no longer paste it. Nothing to do if the table is pasted in `~/.claude/CLAUDE.md`: the hook sees its heading and stays silent. If the table reaches the session another way (an `@import`, a project `CLAUDE.md`, `CLAUDE.local.md`, account instructions, a file with CRLF line ends) it loads twice: turn the option off with `/plugin configure memory@mili-ssm` (`offload_table`). A stale pasted copy wins over the plugin's until you delete it. No eval covers this table's delivery yet (ADR 0032).

### Fixed

- `memory-curator` proposes `--claim` together with `--short` when a lesson is wrong in a detail, so a reworded lesson keeps loading at session start; it now covers the "short forms nobody read" block of the queue, keeps the proposals it did not apply in apply mode, and returns a partial table by its 12th tool call.
- `memory-synthesizer` and `memory-researcher` stop with a report before their turn limit; `memory-researcher` names the only commands it runs; `memory-recorder` no longer confirms a lesson marked `from transcript, unconfirmed`.
- The `memory` skill says when to write memories inline (one) and when to hand them to `memory-recorder` (two or more, or raw material); `memory-curation` says the same `--short` rule for a lesson wrong in a detail.

### Changed

- When curation is due, the session start text now ends with `(after the current task: dispatch memory:memory-curator).` instead of telling the model to run `mem curate`, so the main model hands the pass to the cheap curator. Nothing to migrate.
- Contributors: the engine test suite runs in parallel (`pytest-xdist`, `-n auto`, and a shared uv cache: about 30 s instead of about 5 min on 20 cores, no network once the uv cache is warm); `bin/mem-capture` reads `MEM_CAPTURE_LOCK_POLL` (seconds between lock attempts, default 5; a test hook); the README command is updated. No change for users.

## [0.14.0] - 2026-11-25

### Changed

- `memory-status-checker` description names when to use it (resuming work, before choosing the next task, asking about the state of the work, docs or git), with two example questions, instead of "whenever you need", so the main model delegates to it more readily. Nothing to migrate.
- The status-checker row of `user-config/offload-policy.md` names the moments (work resumes, before choosing the next task, the owner asks where things stand) and says to dispatch it before reading plans or the backlog yourself, instead of "your judgment". **Paste the table again** into your `CLAUDE.md` to get it.

### Added

- The session start text gains one line pointing at `memory-status-checker` when the project has a live state memory, so a resumed project names the agent at the moment it applies. Nothing to migrate.

## [0.13.0] - 2026-11-25

### Added

- `memory-status-checker` subagent (Haiku, read-only): when you resume earlier work, it reads git, the open-work and plan documents and the project's state memories, and returns one status card with a date and a source on every line, the written state that git or a newer memory shows to be out of date, and the next steps as the project wrote them. Ask it follow-up questions with `SendMessage`. Not measured yet.
- An offload table for your user-level `CLAUDE.md`, `user-config/offload-policy.md`: when to hand memory work to each of the five subagents and what each returns. Paste it to have the main model delegate (README § Subagents); nothing changes until you do.
- `mem curate` now lists an established lesson whose short form the automatic fill will not write: it gave up after two failed tries, or the lesson is repository-tracked, or a project lesson of weight `strong` you have not confirmed ("no short form", with the `mem memory edit m:<h> --short '<text>' --topic <t>` that fixes it), and the session-start "Curation due" count includes it until a `mem curate --done` pass. `mem rules --more` says those lessons need curation instead of promising the background pass will write them, counting only the lessons it left without a short form. Nothing to migrate.

### Fixed

- The subagent start text is no longer given to `memory-synthesizer`, as the README already said. Nothing to migrate.

## [0.12.0] - 2026-11-24

### Security

- Writes into memory folders no longer follow symlinks (a cloned repository could plant one to overwrite a file elsewhere): files are replaced through unpredictable temporary names, logs are appended without following links, and a symlinked project `.memory` folder or entry is ignored. Global memory folders may still be links (synced folders). Nothing to migrate.
- Memories committed to a repository (tracked `.memory/*.md`) never show as owner-vouched: the owner confirmation written in their file no longer counts, and they are marked "(from repository)". They still load and qualify as rules through their session sightings.
- Every other write into memory folders and the note store (note creation, rename, index READMEs, curation and settle logs, restore, import, state files, `mem-corroborate undo`, log trim, `.gitignore`) no longer writes through a symlinked file or a predictable temporary name (a folder inside the note store may still be a link, as the owner may set one up); `mem import` skips symlinks in the source (files, folders, `topics.yaml`) and in the destination, and lists each skipped path.
- Corroboration (global lessons, sightings, the short-form and topic fill, rewording) leaves out memories a repository commits: they still load at session start, but are never lifted into global memories and never written to by the background job.
- `mem fetch-sources` refuses a host that resolves to a non-public address (loopback, private, link-local, metadata), at the first URL and at every redirect, through the same address-checked transport as `mem-research`. The connection is pinned to the checked address, so it ignores `HTTPS_PROXY`; a network that needs a proxy cannot fetch sources. A download now has a 120 s total limit and 10 redirects at most, and its errors read like `HTTP 404`.
- Background curation and synthesis sessions (`mem-auto`, `mem-synthesize`) run in a sandbox: they read only the store, the global memories folder, their work folder and the plugin's own skill files (other registered projects' memories are off: `--project` and `--all-projects` are refused), run only the `mem` subcommands their briefs use, and cannot reach the network (`mem import`, `mem fetch-sources`, `mem new --url` and body files outside those folders are refused there), so text injected into a note cannot make them read local files or send data out. Nothing to migrate.

## [0.11.0] - 2026-11-23

### Added

- New skill `memory-research-wave`: a procedure for a research wave (several sources or several agents) into the store: leads, parallel writers that work from full page text, a fresh-context fact-check per area, one fixer, a review of the whole and a lesson with the wave's figures. Nothing to migrate.
- The `memory` skill gains a reference, `references/research-notes.md`, with the rules for writing `literature` and `knowledge` notes from sources: source ranks 1 to 5 and what each may support, the `confidence` rubric, `Inference:` labels, declarative filenames, local copies with `mem fetch-sources`, and fact-check results. Nothing to migrate.
- The session-start text now adds up to two lines about the store, each only when its count is above zero. `History: N changed notes held back from the last commit: run mem check.` means the last history commit left notes out because they fail `mem check`: run `mem check` and fix what it reports. `Re-read due: N notes are past their review date: mem review.` counts the llm notes that `mem review` lists as due for re-testing or re-reading: run `mem review` and re-read them when the task touches that topic. The count of due notes is refreshed once a day and kept in the plugin's data folder (`due-counts.json`), so a note edited or re-read today leaves the count from tomorrow. Nothing to migrate.

### Changed

- The session-end history commit (and the automatic curation and settling that start after it) now runs detached from the hook, because Claude Code gives all SessionEnd hooks one 1.5 s budget that could cut the commit short. The commit appears a moment after the session ends; the hook log (`hooks/log.jsonl`) gets a `started` and a `done` record for it, and a `started` without a `done` means it was killed (30 s limit). Nothing to migrate.
- History commits (session end, curation pass, `mem history commit`) now hold back a changed note that fails `mem check`, so a broken note is not pushed to the store's remote; the other changed notes are committed. A held-back note stays in the working tree. `mem history commit` and the session-start line list only the notes that fail `mem check` (run `mem check`, fix what it reports); the next commit takes them once they pass. A note you edited while the check ran is also left for the next commit, silently. The check runs on the working tree, not on the committed snapshot, so a committed note may link to a note that is still held back. Nothing to migrate.
- The session start and every `mem` command start faster (the session-start hook about 40% less, `mem search` about a third less, measured before this release). Notes read the same as before, with one difference: a note whose frontmatter has a tab right after a colon (`key:\tvalue`) is now accepted instead of reported by `mem check`, and other frontmatter errors are worded slightly differently. Nothing to migrate.

## [0.10.0] - 2026-11-23

### Changed

- The session start line `Curation due: N items (<parts>) (run mem curate after the current task).` now counts the decision items the last `mem curate --done` did not list: written again after being refuted, same or opposite, newer state, expired, seen often, not confirmed in 90 days. New memories alone no longer count, and no line appears at 0. `at least N` means the count is incomplete: the start-time pair search used up its budget, or one folder's count failed. Nothing has to be done, but until the first `mem curate --done` after the update the first sessions count every expired, seen-often (project) and not-confirmed item and the pairs with a memory changed since the last pass, including items that waited before; running `mem curate` and `mem curate --done` once clears them. The background curation (`auto_curation`) does not record a pass, so the line stays until someone runs `mem curate --done`.
- `mem curate --done` records the keys of the items the queue held in `curated-items.json` in the data folder (`curated.json` keeps its format) and prints `recorded K items (<scope>)`.
- `mem remember` no longer prints "N new memories since the last curation pass"; its list of related memories names the pairs a new memory makes.
- `mem curate` groups the same-or-opposite pairs by memory (the memory in most pairs first, then each partner with its claim and a `differ in` line). `differ in` leaves out stopwords except negations, keeps digits and says `wording only` when nothing is left, in the notes queue too. The seen-often block lists project memories only and asks `general enough for a global lesson?` (`mem promote <h>` drafts a `mem remember --global --kind lesson`; a global memory cannot be promoted).

### Added

- `mem curate` lists pairs of live state memories of one project as `newer state of the same project?` (the older memory, then `-> ` the newer): settle with `mem supersede <old> <new>` or `mem distinct <a> <b>`. The `memory-curator` agent proposes it as a `supersede` row and never applies it with `mem curate apply --safe`.

## [0.9.0] - 2026-11-23

### Added

- The option value `rules_layout: digest` (and `mem rules --layout digest`) prints the loaded lessons under a heading per topic that says when it applies, with a line for each global lesson written for that heading. Off by default; where a text is missing or stale the short form or the bare topic prints, so nothing breaks. Nothing to migrate.
- `mem-corroborate digest [--dry-run] [--sheet FILE]` writes those texts with two small-model sessions (one writes, one checks each line against its lesson); with `rules_layout: digest`, `auto_capture` on and loaded rules on, the background pass runs it. It changes no lesson.
- The index line after the rules names what each topic is about when the topic has a heading.

### Changed

- Lessons that load at session start are no longer limited in number: they fill up to 3200 characters of rule lines (was 16 lessons and 2400 characters), and the index line of the lessons left out may take up to 1600 characters (was 200), so it names more topics. Nothing has to be done; the session start text can be longer.

## [0.8.0] - 2026-11-23

### Added

- The option `auto_reword` (off by default; it needs `auto_capture`) lets the background pass reword the short form of a loaded lesson that got worse, once for each wording you wrote or read, with the same checks as a first short form; a reworded lesson shows in `mem rules --unread`. The pass never rewords its own rewording nor a wording you kept with `mem triage accept`: those come to you. `mem-corroborate reword` runs the step by hand (`--dry-run`, `--sheet FILE`). Its gate passed on one store (15 lessons); read `mem rules --unread` after it runs.
- The option `rules_layout` (`flat` by default, or `grouped`) and `mem rules --layout` print the lessons loaded at session start under a heading per topic; the same lessons load, only the text changes. Nothing has to be done: the default is the old layout. The grouped layout is not measured yet.

## [0.7.0] - 2026-11-23

### Added

- Each lesson now keeps a log of dated cases (`worked`, `failed` or `seen`, taken from what the capture saw) and the versions of its short form, each with its tally; `mem show` prints them. A lesson that got worse after it loaded is marked in `mem rules` and `mem rules --more`, listed by `mem curate` under "balance got worse after loading", and counted in the session start text ("Got worse: N loaded lesson needs a decision"). It keeps loading until you decide: reword it or go back to an earlier text (`mem memory edit <h> --short`), drop it (`mem forget <h>`), or keep the wording with the new `mem triage accept <h>` (`--project-scope` for a project lesson), which stores a `reviewed` date. `mem confirm` and `mem remember` take `--outcome` and `--seen-on`; the corroboration pass carries cases to the general lesson.
- Records written before, and older plugin versions reading a store written by this one, keep working: there is nothing to migrate.

### Changed

- `mem confirm --source` on a session the lesson already counts, given with `--outcome`, now adds that case, prints `m:<handle>\tcase <outcome> added` and exits 0; without `--outcome` it still changes nothing and exits 3. `--outcome` or `--seen-on` without `--source`, and a `--seen-on` later than today, are usage errors.
- The log line of the corroboration pass has one more key, `cases`: the case entries it carried to general lessons.
- Up to 16 lessons (was 6) and 2400 characters of rule lines (was 900) now load at session start, so more established lessons reach the agent without asking by topic; nothing has to be done.

## [0.6.0] - 2026-11-22

### Added

- With `auto_capture` on (and `loaded_rules` not `false`), the background pass now writes the short form and topic of established lessons that lack one, and they load at the next session start **before anyone has read them**. Code refuses a short form that drops its claim's hedge, adds an absolute word, holds a link or says "owner"; a second model session checks the rest against their claims. A short form is tried twice at most per wording of a claim; after the second refusal a general lesson waits at triage with the reason (`mem triage hold <h> --because TEXT` does it by hand). A `strong` project lesson is filled only after you confirm it. Measured once before release, by a gate on a private copy of one store (the plugin README gives the figures and what they do not show); a short form that keeps its hedge but loses the situation of its lesson is not caught, so read `mem rules --unread` now and then. To see what loaded unread: `mem rules --unread` (also counted by `mem curate`); to mark them read: `mem rules --read <h>...` or `--read all`; to switch one off: `mem memory edit <h> --no-load`; to switch all off: option `loaded_rules` to `false`. `mem-corroborate status` prints a `last fill:` line.

### Changed

- A general lesson waits at triage on its first establishment only when its weight is `strong`; a `medium` or `light` one is released and may load once it has a short form. Pending ones stay pending.
- `mem memory edit --short` and `mem remember --short` now check the text against the claim: a text that drops the claim's hedge, adds an absolute word, holds a link or says "owner" is refused (exit 2, with the reason), and an accepted one is marked as unread by a person. Pass `--user-read` for a text you read yourself (no check, no mark). Stored short forms are not touched.

## [0.5.0] - 2026-11-22

### Added

- Established lessons can load at session start as short rules (at most 6, 900 characters), followed by one line that counts the other recommendations by topic; `mem rules` prints them and `mem rules --more [<topic>]` lists what did not load. A lesson loads only when it has a short form, so **nothing loads after the update until you give lessons one**: `mem-corroborate fill --dry-run --out FILE` has a small model propose a short form and a topic for up to 30 lessons, in a file that also carries each lesson's load state (`yes`, `index` or `no`) for you to set (it starts one model session and sends lesson text to it), you read and edit the file, then `mem-corroborate fill --items FILE` applies it (no model session; `mem-corroborate undo <stamp>` reverts it). Or write one by hand with `mem memory edit <h> --short TEXT --topic TEXT`, or `mem remember --short --topic`. `mem memory edit <h> --no-load` turns one rule off and `--index-only` keeps it to the index line; `--load` removes either. Editing a claim removes its short form. The plugin option `loaded_rules` (on by default) set to `false` loads no rules and prints no index line at session start; `mem rules` still shows what would load. Rolling back to the previous version keeps the new record fields (`short`, `topic`, load state). Nothing to migrate.

### Changed

- The capture now also keeps, as an unconfirmed lesson, a step you asked for on your own that visibly paid off (for example one more review before publishing), so that a later session may take that step without being asked. Nothing to migrate.

## [0.4.1] - 2026-11-22

### Fixed

- The background capture and the corroboration pass now find the global memories folder from the store (`MEM_STORE`, or the default store) as `mem` does. Before, with no `MEM_MEMORIES` set, they saw no global memory: since 0.3.0 the capture could propose again a lesson that a global memory already held, and in 0.4.0 the pass could not add a sighting to a global record. Nothing to migrate; the next capture and pass read them.

## [0.4.0] - 2026-11-22

### Added

- A general lesson captured from a transcript now gets one global record that stays in quarantine: searches, the session start text and `mem memories` do not show it until it is seen in a second project (three sessions across two projects for a `strong` one) or the owner confirms it with `mem confirm <h> --global --by-owner`. `mem memories --global --quarantine` lists what waits. **Migration:** before you install this version, confirm with `--by-owner` every global memory of origin `transcript` that you want to keep readable: one seen in fewer than two projects (every one written before this version, since sightings did not name a project) would otherwise be hidden.
- With `auto_capture` on, a background pass (`mem-corroborate`) starts after a capture that wrote something. A small model proposes which lessons state the same lesson, a second session verifies each proposal, and only verified ones are applied: duplicates inside a project are merged, a general lesson gets its global record, and later sightings are added to it. It sends lesson text to the model, costs up to two sessions per pass within `auto_capture_budget` each, and can be undone per run with `mem-corroborate undo <stamp>`. `mem-corroborate status` and `ack` report and clear a failed pass.
- A lesson that leaves quarantine waits for triage: `mem curate --global` lists it and the session start text counts it. `mem triage accept <h>` keeps it, `mem triage reject <h>` retires it and marks its project records so they are not promoted again, and `mem memory edit <h> --global` rewords it.
- With `auto_capture` on, a session start also captures sessions in the transcript folder of the starting session that were left open and never ended (idle for 6 hours, at most 7 days old; at most 2 per start and 4 per day use the model, at the cost of an ordinary capture).
- A capture that recognizes a lesson already kept as a global record adds a sighting to it, naming the project by an opaque key and never copying text of the transcript.


## [0.3.0] - 2026-11-22

### Added

- New option `auto_capture` (off by default): when a compaction starts and at session end, a background run reads the new part of the session's transcript and writes lessons as unconfirmed project memories (`auto_capture_budget`, USD per window, default 0.25). Turning it on sends transcript text of the session to a small model through your own `claude` and spends model usage; a failed run shows one line at the next session start until `mem-capture ack`. Not yet measured. Nothing to migrate.
- Memories can now come from a session transcript: they are marked `from transcript, unconfirmed` until another session shows the same lesson, and lapse 30 days after the last session that showed them. `mem remember` takes `--reach` and `--weight`; `mem confirm` takes `--source` and `--note` to record one more session; `mem curate` has a new category for these records; `mem-capture run --write` records the kept candidates as project memories. No hook runs it yet. Nothing to migrate.
- A trial command `mem-capture run` proposes memory candidates from a session transcript into a local file; it writes nothing to the store and no hook runs it. Nothing to migrate.
- After a compaction the summary ends with a handoff block (task, state, next step, verified, unverified, plan) and lists the items not yet recorded; the agent is told only when the block is missing or names a plan file that does not exist. Nothing to migrate.

## [0.2.0] - 2026-11-19

### Changed

- A note that a sentence of its synthesis cites goes stale only when such a sentence, or a table row of its part, changes; a note no sentence cites still goes stale on any change to its part, and stamps written before keep that whole-part rule until the note is stamped again.

### Fixed

- A web page whose `<script>` or `<style>` is never closed no longer hides the text from its next tag on, so a quote there is found by the research checks; script source before that tag may still count as page text.
- `mem import --research-data` now scans every text file it copies (`.txt`, `.json`, ...) for secrets and hard terms, not only Markdown.
- A write to the global scope is refused, with a message, when neither `HOME` nor `XDG_CONFIG_HOME` is set (exit code 2, nothing written), because the forbidden-terms list cannot be located; project writes are unaffected.
- `mem memories --project NAME` says so on stderr and exits 2 when the registered project's memory folder was moved or deleted, instead of printing nothing.

## [0.1.0] - 2026-11-19

### Added

- First versioned release of the `mem` command and its skills and agents: search, read and record notes and memories, curation passes, syntheses. License: MIT.
- Still under active development: while the version is `0.y.z`, a minor version may change commands or the store layout; the changelog says how to migrate.
