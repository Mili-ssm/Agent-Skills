# memory

Notes and memories reachable from every repository and subagent, through the `mem` command.
ADR 0023; see the [stage plan](../../docs/superpowers/plans/2026-11-17-memory-plugin.md).

## Install

`/plugin install memory --marketplace Mili-ssm/Agent-Skills`

## Requirements

[`uv`](https://docs.astral.sh/uv/) on the path. Without it `mem` exits 127.

## Two kinds of record, two scopes

| | Note | Memory |
|---|---|---|
| What | A general statement with its source | Something seen or decided once, in a context: experience, not fact |
| Where | The store | The project's `.memory/` folder by default; a global folder with `--global` |
| Written with | `mem new` (a paper or other source is a `literature` note with its `--url`; `mem fetch-sources` keeps a local copy outside git and `mem passages` reads it) | `mem remember`, `mem observe` (kinds: decision, constraint, pitfall, lesson, finding, document, state) |

`mem search` prints matching memories first, labelled `[memory: …]`, then notes.

## Folders and how they are set

| Folder | Set by | Notes |
|---|---|---|
| Store (notes) | Nothing to set: the default store is created on first use (`mem init`). Or the plugin option `store`, `MEM_STORE`, `--root` | A store is read-only unless it holds a `mem-store.yaml` marker; the default one has it. An existing folder of notes without the marker is never made writable by this tool. To sync, make the store a git repository and push it to a remote of your choice |
| Global memories | Plugin option `memories`, or `MEM_MEMORIES`; else `memories/` in a writable store | May not be inside a read-only store. Nothing specific to a project belongs here. `mem terms add <term>` lists a hard term (a write that contains it is refused); `mem terms add <term> --soft` lists a soft one (the agent must ask the owner); `mem terms list` and `remove` manage them |
| Other projects | A local registry, filled as memories are written (`mem projects list`) | Never read by default. `mem search "<q>" --project <name>` or `--all-projects` includes them, each under its own header; the registry holds names and paths, stays on this machine and is not synced |
| Project memories | The main worktree's `.memory/` | Kept out of git through `.git/info/exclude`, added once when the folder is created; remove that line to commit the folder |

## Compaction hooks

| Hook | What it does |
|---|---|
| `PreCompact` | Asks the summary to end with a handoff block: task, state, next step, verified, unverified, plan file |
| `PostCompact` | Reads the block from the summary and checks that the plan file it names exists. Logs one line per compaction to `hooks/log.jsonl` (counts, booleans, field names, the trigger and the session id; no text of the summary and no path). Speaks to the agent in two cases only: no handoff block, or the block names a plan file that does not exist |

`docs/studies/scripts/memory_usage.py` reads these logs.

## Bringing in existing notes

`mem import <folder> [--dry-run] [--overwrite] [--with-sources] [--research-data]` copies the `literature/` and `knowledge/` files, the Markdown files and figures of `research/` (its data and code only with `--research-data`) and the topics of an older folder of notes into the store, reading the source only. Files that differ stay as they are and are listed, unless `--overwrite`; imported text is not checked for secrets or terms, only reported.

Plugin options take effect in the next session: a `SessionStart` hook exports them to shell commands and writes them under `$XDG_CONFIG_HOME/agent-memory/`.

## Syntheses

A synthesis is the long version behind a group of notes: one indexed document per subject with origins, reasons, and when a thing applies and when not. `mem synthesis new|add|append|edit|attach|list` build it one cited part at a time; `rename`, `remove` and `detach` change a part or a note's link, and `topics` sets the synthesis's topics, `refs` adds or removes inline note references from a file of `section | unit | add|remove target` lines without retyping any text (`mem restore s:<handle>` undoes a step); a note says which part it recalls (`part of:`), and `mem search` prints matching parts after the notes. Notes are written loose; a curation pass (`mem curate --notes`) joins them to a synthesis, lists notes to unify (`mem unify`) and topics that have enough notes for one. The `memory-synthesis` skill holds the procedure. `mem-synthesize --backfill [s:<handle> ...]` adds the references to syntheses that have none: one read-only Haiku session per synthesis (Read only, no shell, web or write) proposes which source note supports each sentence and code applies them with `mem synthesis refs`; `--dry-run` lists the parts and the estimated cost, and a part already done and unchanged is not sent again. Writing a synthesis with `mem-synthesize` ends with the same step (about 0.05 USD each; a failure there leaves the synthesis as it is and does not fail the topic; `--no-references` skips it).

A project can also keep stamped syntheses in `.memory/syntheses/` (`organization`, `plans`, `pending`, `conventions`): each `## ` part ends with the files it covers and the commit it was written at. `mem project-synthesis add <name> "<heading>" --paths a,b --body-file F` writes or replaces a part, `confirm p:<name>#<handle>` re-stamps it after you checked it, `list` shows each part's freshness, and `mem show p:<name>[#<handle>]` reads it, marking a part whose files changed since as possibly stale. They need no store and never write to one.

## Subagents

They keep the main conversation's context on the task.

| Subagent | Given | Does | Returns |
|---|---|---|---|
| `memory-researcher` (Haiku) | A question | Answers from the memory, deeper sources if needed, outside research only for what is missing, which it records as findings | Conclusions with their references, and what is new and unchecked |
| `memory-recorder` (Sonnet) | An account of what happened, or logs and files | Writes the few memories worth keeping, each in its scope; optionally lists the curation queue | What it recorded |
| `memory-curator` (Haiku) | Nothing | Reads the curation queue | A table of proposed actions; it applies none |
| `memory-synthesizer` (Haiku) | A topic and a slug | Writes one synthesis from the topic's notes, only through `mem synthesis`; stops when the topic has too few notes | Parts, notes left out, `mem check` result and the notes to attach |

The start text every other subagent receives is not given to these four: they carry their own instructions.

## Curation

`mem curate` lists what needs a decision (memories that say the same or the opposite, expired ones, ones seen several times, ones nobody confirmed); `mem merge`, `refute`, `distinct`, `supersede`, `forget`, `confirm` and `promote` carry a decision out, and `mem restore` undoes the last one on a memory. Records change only through commands, never by editing files: `mem note edit` corrects a note (claim, topics or one section) and `mem memory edit` a memory (`mem restore` a retired one first). `mem note confirm` adds a source-backed line to a note's evidence and `mem note dispute` marks the note `[disputed]` (a claim a source contradicts: check it before relying on it; `--clear` removes the mark); a memory marked `web, unconfirmed` is a web finding no second source has confirmed. Nothing is deleted. The session start text says when a pass is due; the `memory-curation` skill holds the procedure and the `memory-curator` subagent proposes actions without applying them.

## Automatic curation (off by default)

Plugin option `auto_curation` (exactly `true` turns it on; any other value is off). **What starts it:** the `SessionEnd` hook, after its commit, starts `bin/mem-auto run` detached (it outlives the session; the claude binary is `CLAUDE_CODE_EXECPATH`, `claude` on `PATH`, or the hook's parent process). The run counts the global memories and notes written since the last run ended (so its own edits do not count) or the last curation pass (`mem curate --new-since`; an edit counts) and goes on only when the count reaches `auto_curation_threshold` (default 10); right after a run the count is 0.

**What it does:** takes the store-wide run lock first (one run at a time; while it holds it, `mem curate --done` does not trim logs and the session-end hook does not commit), writes status `running`, runs the `memory-curator` in apply mode (only `mem curate apply --safe` changes anything) and then `mem-synthesize` for store topics with 8 notes or more and no synthesis. The last step of `mem-synthesize` adds inline note references to each synthesis it wrote (one read-only Haiku session, about 0.05 USD; `mem-synthesize --no-references` skips it, `mem-synthesize --backfill` adds them to existing syntheses, `mem restore s:<handle>` undoes them). Hooks are off in its sessions, so they cannot start another run. It never records `mem curate --done`.

**Bounds:** `auto_curation_budget` USD per run (default 2); every session also gets `--max-budget-usd` of what is left, and no step starts when nothing is left. A session that ends without a cost report (killed at its timeout) fails the run and starts no further session. No per-day cap and no retry limit, because the threshold is the throttle.

**Where to look:** `mem-auto status` (last run: time, state, cost, reason, log), `mem-auto due` (count, threshold, would it start), `mem-auto ack` (clears a shown failure). State and logs sit in `<state folder>/auto/<id>/` (mode 0700, runs kept 30 days). After a failed run (or a `running` older than one hour) the next session start text carries one line, `Automatic curation failed on <date>: <reason>; log: <path>`, until `mem-auto ack`; a success adds nothing. Every change is undone with `mem restore` or the store's git history.

**Turn it off:** unset the option. **Kill criteria** (owner's call to turn it off): a run costing more than its budget (shown as a failure), two failures in a week, or usage growing beyond what the owner wants.

## Settling new memories (engine commands, and the background run below; the run is not yet measured)

`mem settle` is the engine side of judging new global memories against their look-alikes (stage W of `docs/superpowers/plans/2026-11-17-memory-seamless.md`; the background run that uses it is described after this table). Global memories only; project memories and notes are never touched. State and log sit beside the global memories (`.settle-state.json`, `.settle-log`; the store's `.gitignore` keeps both out) and the automatic run's state (`mem-auto`) is never read or written.

| Command | Does |
| --- | --- |
| `mem settle pending [--json]` | The queue pairs (`mem curate` pairs) of two live global memories where one is not yet judged; prints nothing when there is none (the examined records are then judged and `due` stops reporting). A record written by a pipeline is never the new side. The first use of the feature marks every memory that exists as judged |
| `mem settle apply --verdicts FILE` | FILE: a JSON list of `{"a", "b", "decision": "merge"\|"supersede"\|"distinct"\|"nothing", "reason"}`. A row is refused, alone, unless its pair is one `pending` lists now; merge and supersede always act on the older record: the one not yet judged is the newer, else the later `created`; on the same date merge and supersede are refused (only distinct or nothing). A pair with flagged words is never merged. Same code and undo records as `mem merge`, `supersede`, `distinct`. Afterwards what the last `pending` showed is judged, except the handles of a pair whose row was refused or missing: it is offered once more, then logged as `left` and judged. If an action fails after a file changed, the change is logged as `partial` and `undo` restores it |
| `mem settle log [--all]`, `mem settle ack` | Settlings not yet acknowledged (number, date, decision, shortened claims); acknowledge them all |
| `mem settle undo N` | (`pending`, `apply` and `undo` take a lock: a second one exits with a message.) An unreadable state file is an error, never replaced. Puts both records of settling N back in one step; refused, changing nothing, when a record changed again since |
| `mem settle due --minutes M` | Exit 0 and the count when new memories wait and the last `apply` ended more than M minutes ago (or never); else exit 1 |

### Automatic settling (off by default; not yet measured)

Plugin option `auto_settle` (exactly `true` turns it on) and `auto_settle_minutes` (least time between runs, default 30). **What starts it:** the `SessionStart` hook exports `MEM_SETTLE_AUTO`, `MEM_SETTLE_MINUTES` and `MEM_SETTLE_CLAUDE` (the claude binary) to the session's shell commands and creates the settle state, so the first write is not taken as already judged. A `mem remember` or `mem memory edit` of a global memory then checks `mem settle due` (one state file) and, when it is due, starts `bin/mem-settle run` detached; the write is never delayed or failed by it. Without those variables nothing starts, so trials and tests never trigger it; records written with `--origin pipeline` never trigger. The `SessionEnd` hook starts the same run with `--minutes 0` for what is left.

**What it does:** one run at a time (a second exits silently); `mem settle pending` writes the pairs to a work folder, and with none the run ends without a model. Otherwise one Haiku session (effort medium, budget `--budget`, default 0.25 USD) reads the pairs and writes `verdicts.json`. It has no Bash, because a session with `Bash(mem *)` could run any `mem` command and bypass the limits `mem settle apply` enforces; Python applies the file. A session that fails, has no cost report or leaves no valid list changes nothing and is a failure; a failed run waits `--minutes` before the next. It never reads or writes the `mem-auto` status.

**Where to look:** `mem-settle status`, `mem-settle run --dry-run`, `mem-settle ack` (clears a failure line); state in `<state folder>/settle/<id>/` (runs kept 30 days). The session start text shows one line while unacknowledged settlings exist (`settled since <date>: 2 merged, 1 superseded, 1 left; see mem settle log, undo with mem settle undo <n>, hide with mem settle ack`) and a failure line after a failed run. **Not measured:** the 40-record trial of the plan decides whether it is turned on; kill criteria there.

### Automatic capture (off by default; not yet measured)

Plugin option `auto_capture` (exactly `true` turns it on) and `auto_capture_budget` (USD per window, default 0.25). **What it does:** when a compaction starts and when a session ends, a background run reads the new part of the session's transcript with a small model and writes lessons as unconfirmed project memories, shown `from transcript, unconfirmed`. The `PreCompact` and `SessionEnd` hooks start `bin/mem-capture auto` detached and never wait on it. Turning it on sends transcript text of your session to a small model through your own `claude`.

| Limit | Value |
| --- | --- |
| Where | Only a project that already has its memory folder: the project of the session's folder, or the one `MEM_PROJECT` names when that variable is set in the session's environment (it wins, as for every `mem` command) |
| Per trigger | At most 3 windows (a window is one stretch of the transcript, up to 80,000 characters of extract, read by one model session); no further window once 5 new records are written; the rest is read at the next trigger |
| Compaction | The run starts with the compaction (`PreCompact`) and waits 5 minutes before it reads, so the records the session writes itself land first |
| Session end | The last part of a session is not read at its end when the session ends without its `SessionEnd` hook (a killed terminal, a conversation left open in an editor tab), when another capture holds the lock for more than 15 minutes, or when the trigger stops at its window or record limit. The sweep below reads it later |
| Sweep | A session start also reads sessions in the transcript folder of the starting session that were left idle: not changed for 6 hours, at most 7 days old, with unread lines, in a project that has its memory folder. At most 10 files are examined per start; at most 2 per start and 4 per UTC day use the model, each as an ordinary trigger (up to 3 windows within `auto_capture_budget`); a file that did not change is skipped |
| Rewording | A lesson reworded is recorded twice by the capture; the corroboration pass below merges the two |
| Evidence | Not yet measured |

**Where to look:** `<data folder>/capture/` holds `status.json`, `log.jsonl` (one line per trigger: the session's id, counts and a short reason; no claim text, no path) and `runs/` (the newest 20 runs, none older than 14 days; it holds session text, so keep it private). After a failed run the next session start text carries one line, `Automatic capture failed on <date>: <reason>; log: <path>`, until `mem-capture ack`.

### Corroboration, quarantine and triage (with `auto_capture`; measured once, on a copy)

**What it does:** after an automatic capture that wrote something, `bin/mem-corroborate` runs in the background. It shows a small model the lessons of every registered project and the global ones as lines with opaque ids, and applies only what two sessions agree on:

| Step | Who | What |
| --- | --- | --- |
| Propose | Model session 1 | Groups of lessons that state one lesson, each with one wording that names no project |
| Verify | Model session 2, which sees one group at a time | Same lesson? Faithful wording? A lesson about method that holds outside its project? |
| Apply | Code, through `mem` | Duplicates inside a project are merged; a general lesson gets one global record; sightings are added to it; the project records are linked to it |

| Rule | Value |
| --- | --- |
| Quarantine | A global record from a transcript is hidden from searches, the session start text and `mem memories` until it is corroborated. `mem memories --global --quarantine` lists it |
| Corroborated | `light` and `medium`: seen in two projects. `strong`: three sessions across two projects. Or `mem confirm <h> --global --by-owner` |
| Triage | A lesson that leaves quarantine is listed by `mem curate --global` and counted in the session start text until `mem triage accept <h>` or `mem triage reject <h>`; reword it with `mem memory edit <h> --global`. The background curator never runs `mem triage` |
| Wording | A lesson is reworded once, when its global record is written; later evidence only adds sightings |
| What counts as a project | A registered project whose folder exists, holds a memory folder and is not under a temporary folder; it is known by a hash of its path, so a moved folder or a second clone counts as another project |
| Cost | Two model sessions per pass, each within `auto_capture_budget`; no pass when no lesson changed; after two passes that fail on the same lessons it stops until one changes |
| Undo | `mem-corroborate undo <stamp>` restores every file a pass changed; `<stamp>` is a folder name under `<data folder>/corroborate/runs/`. It refuses, changing nothing, when one of those files was edited since |
| Lapse | An unconfirmed lesson gets an end date 30 days after its last sighting; a new sighting within 60 days after that date revives it. A lapsed lesson stays stored and in quarantine; `mem memories --global --quarantine` still lists it |
| What is sent to the model | The claim and context of every lesson of origin `transcript`, from every registered project and the global folder; no transcript text and no project name beyond what a lesson's own text says |

**Where to look:** `<data folder>/corroborate/` holds `status.json`, `log.jsonl` (counts only), `seen.json` and `runs/` (private: it holds lesson text). `mem-corroborate run --dry-run --out FILE` runs both model sessions (up to `--budget` each, default 0.25 USD), writes what a pass would do to FILE and changes no record. After a failed pass the session start text carries one line, `memory: the last corroboration pass failed (<reason>)`, until `mem-corroborate ack`; `mem-corroborate status` shows the last run.

**Evidence and limits:** on a private copy of real records (36 lessons, 3 projects), 6 of 7 dry runs gave a usable answer (the seventh used line numbers as ids, was refused by code, and the brief was corrected; 3 of 3 after that); the 6 proposed the same 15 groups; a run applied 12 to 15 of them, every refusal for an unfaithful rewording; the owner accepted 15 of 15. Not measured: use over time, lessons of more than one project, and whether a released lesson stops a failure from recurring. Only records of origin `transcript` are read: a global memory written by hand is never merged or given sightings.

### Capture trial (`mem-capture run`; writes to the store only with `--write`)

`mem-capture run --transcript PATH --out FILE [--project DIR] [--since-line N] [--model NAME] [--budget USD] [--write]` reduces one session transcript to an extract and has one headless session (no Bash, no hooks) propose memory candidates; a program keeps only those whose evidence is copied from the transcript. The result file (mode 0600) holds the kept and dropped candidates, the cost and the line range; it holds session text, so keep it private: `--out` must be outside any repository (a folder with a `.git` entry in it or above is refused) and must not be a symlink. Defaults: model `haiku`, budget 0.25 USD per run (`--budget`); the work folder is temporary and removed at the end (`--keep-work` keeps it). `recorded.txt` gives the session the live claims of the project and of the global scope. With `--write`, code (never the model, which has no Bash) records each kept candidate through `mem`, so every check `mem` makes at writing applies; it writes in the project scope only, never the global one. A record starts `from transcript, unconfirmed`, with `reach` and `weight` set, and becomes established when distinct sessions have shown it (light 1, medium 2, strong 3); a candidate that names an existing record, or repeats its claim, adds this session as one more sighting, and one session counts at most once however often the command runs. An unconfirmed record lapses 30 days after the last session that showed it. The result file gains `written` (per candidate: `remembered`, `sighting` or `skipped`, with the reason); a failure on one candidate never stops the others or changes the exit code. Without `--write` nothing is written to the memory store. No hook runs `run`; with `auto_capture` on, the hooks start `mem-capture auto`, which runs the same steps per window with `--write` (section above).

## Loaded rules (on a branch, not released; nothing loads until lessons have a short form)

**What it does:** an established lesson that has a short form loads as one line of the session start text, so an agent that never searches still sees it. The text is built by code from the records at each session start; no model rewrites the list. `mem rules` prints the same block, or `No rules loaded.` when none loads.

```
memory: rules learned in earlier sessions. Follow them unless you have a reason not to, and say so when you do not.
- Invented rule 1 (confirmed by the user)
- Invented rule 2 (held in 2 projects)
3 more recommendations by topic: testing 2, process 1 (mem rules --more <topic>)
```

| Term | Meaning |
| --- | --- |
| Loaded rule | A lesson's short form followed by its standing, `(held in N projects)` for a global lesson, `(held in N sessions)` for a project one, `(confirmed by the user)`. The standing is computed from the record, never written by a model |
| Short form | One line of at most 120 characters, kept in the record (`--short`), never stronger than the claim |
| Topic | One or two lowercase words of at most 24 characters (`--topic`), used to group what did not load |
| Index line | The line after the rules: how many more recommendations there are, by topic, ending with `(mem rules --more <topic>)`. At most 200 characters |
| Load state | Absent: the lesson competes for a place. `index` (`--index-only`): never among the rules, counted in the index line. `no` (`--no-load`): nowhere. `--load` removes the field |

**What loads:** a lesson of origin `transcript` that is live, established (not in quarantine), has a valid short form and is not `no` or `index`. A global lesson must also be past triage (`mem triage accept <h>`) or confirmed by the owner; a project lesson needs two sessions or the owner's confirmation. At most 6 rules and 900 characters of rule lines. A project lesson that was generalized never loads twice: when its global twin can itself load and competes for a place, only the twin loads; when the twin awaits triage, has no short form, is index only or is off, the project lesson loads in its own project.

**Order:** confirmed by the owner first, then weight (`strong`, `medium`, `light`), then the number of projects that saw it, then of sessions, then the latest sighting, then the handle. The three best project lessons get the first places. A lesson that does not fit stops the line: nothing ranked lower jumps ahead of it.

**What never loads:** a lesson in quarantine; a lesson with no short form (counted nowhere at session start, unless it is index only: the index line counts an index-only lesson with or without one); a lesson that awaits triage (the `Triage:` line announces it; `mem rules --more` lists it as "awaits triage"); a project lesson seen in one session and not confirmed; a lesson with load state `no`.

**The index line** counts the lessons that qualify and did not fit, plus the index-only ones. A lesson with no topic is counted as `other`, which is why `other` is refused as a topic; when no left-out lesson has a topic the line reads `N more recommendations: mem rules --more`.

| Command | Use |
| --- | --- |
| `mem rules` | The rules block and the index line, as the session start prints them |
| `mem rules --more` | Every lesson left out, grouped by topic, with the reason (over the limit, index only, awaits triage) |
| `mem rules --more <topic>` | Only that group (`other`: lessons with no topic) |
| `mem remember ... --short TEXT --topic TEXT` | Write a lesson with its short form and topic |
| `mem memory edit <h> [--global] --short TEXT --topic TEXT` | Set or change them; an empty text removes one |
| `mem memory edit <h> [--global] --no-load` | Turn one rule off; the lesson stays stored and searchable |
| `mem memory edit <h> [--global] --index-only` | Keep it out of the rules but counted by topic in the index line |
| `mem memory edit <h> [--global] --load` | Remove `--no-load` or `--index-only` |
| `mem-corroborate fill --dry-run --out FILE` | One model session proposes a short form and a topic for up to 30 lessons that qualify and lack either (a lesson with a short form and no topic gets both proposed, and applying the file replaces its short form); the file also carries each lesson's load state, copied from the record, for the owner to set; changes no record |
| `mem-corroborate fill --items FILE` | Apply the file as you left it; starts no model session |

**Giving lessons a short form:** the owner runs `fill --dry-run --out FILE` (the file must not be inside a repository: it holds lesson text), reads it, then runs `fill --items FILE`. Each item holds `id`, `handle`, `scope`, `claim`, `short`, `topic`, `claim_digest` and `load` (`yes`, `index` or `no`). Edit `short`, `topic` and `load`, or delete an item to skip that lesson. An item is dropped when its handle or scope does not match its id, or its record cannot load; it fails when the claim changed since the file was made. A proposal that is not valid (a short form of more than 120 characters, a bad topic) or missing stays in the file with a `problem` field saying why: shorten or fix it, then apply; `fill --items` ignores `problem` and drops an item that is still invalid. `mem-corroborate undo <stamp>` (printed by `fill --items`) puts every written record back while its run folder exists; a later pass may prune old run folders.

**Changing or removing one rule:** reword it with `mem memory edit <h> --short TEXT`; turn it off with `--no-load`. Editing a claim removes the short form, so reword with `--claim` then `--short`.

**Limits:**

| Limit | Why it stays |
| --- | --- |
| A new global lesson has no short form until `fill` is run by hand and its file is read | Nothing unread loads in this release; writing short forms automatically is a later plan |
| A project lesson seen in one session never loads | Nobody has read it |
| A rule may repeat what the owner's own instruction files say | Turn it off with `--no-load` |
| Rules do not reach subagents | The session start hook runs in the main session only |
| `mem-corroborate undo` of a `fill` run works only while its run folder exists | A later corroboration pass prunes old run folders |
| An unexpected error in the middle of `fill --items` stops it with exit 1 and no summary line; the edits already made are kept and can be undone | Each edit is journaled before the next; the count is printed only at the end |
| Nothing checks that a short form is no stronger than its claim | The owner reads every proposed short form before it is applied |
| Every loaded rule gets the same space, not more by weight | Six lines leave nothing to share out |
| With no `store` option set, the hook uses the default store | As for the rest of the session start text |
| The session start text grows by up to about 1200 characters when six rules load | The limits above (115 for the header, 900 for the rules, 200 for the index line) |
| Whether a loaded lesson stops its failure from recurring is read by hand from the capture log | No date on each sighting yet |

**Evidence:** one small task, three runs a condition, a real model, with the rules printed by a throwaway hook, not by this plugin. With no rules, none of three checkable practices was followed (0 of 3 each); with three rules in the session start text, all three in 3 of 3 runs; with the same three among twelve unrelated rules, again 3 of 3, at about 7% more cost than with no rules ([measurement](../../docs/superpowers/plans/2026-11-22-memory-loaded-rules-and-reminders.md#measurement-loaded-rules-are-followed-2026-11-22)). Not measured: a rule that conflicts with another instruction, a long session, and several rules at once in real work. On a private copy of 15 real lessons the small model proposed 13 short forms and 2 passed 120 characters (then dropped; now kept in the file marked with a problem); the owner's reading of them is pending. With this plugin and five of those rules loaded, three runs on one task showed no measurable effect and no harm (the model stated its reading of an ambiguous term in 2 of 3 runs with the rules and in 2 of 3 without); so the evidence that rules are followed is the first measurement, not a run of this plugin.

## Research with the web (`mem-research`; not yet measured)

`mem-research "QUESTION" [--depth memory|contrast|deep] [--contrast NOTE ...] [--store DIR] [--claude PATH] [--budget USD] [--allow-host HOST ...] [--dry-run] [--self-check]` answers from the memory and, by depth, checks knowledge notes and the question against the web (stage 1b of `docs/superpowers/plans/2026-11-17-memory-seamless.md`; the stage's trial decides whether anything else uses it). It prints what the memory says (with references), what the web added (marked **new and unconfirmed**, with its URL), a table of the contrasted notes (confirmed / contradicted / no source), what was dropped and why, and the cost. Plugin option `research_depth` sets the default depth.

| Depth | What it does | Limits for the whole run |
|---|---|---|
| `memory` | only the memory step | 0.25 USD, 3 minutes |
| `contrast` (default) | also the web: up to 5 pages | 0.50 USD, 5 minutes |
| `deep` | up to 15 pages, papers asked for | 2 USD, 9 minutes |

**Steps.** (1) Python runs `mem search` for the question and `mem show` for its first knowledge results; a Haiku session reads that file and writes `need.json` (answer with references, `covers`, up to 3 more searches that Python runs, each as one argument and never through a shell, then one more round and no third, the notes worth contrasting). (2) Only the question and the claims of knowledge notes that pass the secret and forbidden-terms checks are built into the web prompt by code; a question that fails them stops the run before anything is sent. (3) A Haiku session with `--tools WebSearch,WebFetch --strict-mcp-config`, no plugin, hooks off, in an empty folder, with no `MEM_*` or `CLAUDE_PLUGIN_*` variable and no folder holding `mem` on its PATH, returns pages with a stance and a source kind (official, paper, other), never a quote. (4) Python fetches each page itself (http and https, public addresses only, size and time caps; a PDF through `pdftotext` when installed, else not checked) and keeps the passages that share content words with the item. (5) A Haiku session with no shell and no web reads the passages as data and writes `verdicts.json`. (6) Python applies it with three fixed commands (`mem note confirm`, `mem note dispute`, `mem remember --global --kind finding --origin web`) after checking that the quote is on the fetched page word for word, that the URL and stance are the ones the web step returned for that item, that a contradiction comes from an official or paper source (else it becomes no source), and that a finding's numbers are all in its quote and at least 70% of its content words too. A record of origin `web` is never the new side of settling.

A knowledge note of origin `experience` (the owner's own experiments) is never chosen for a contrast by the memory step: it is dropped with "own experience: not sent to the web" and goes to the web only when named with `--contrast`.

No model session has a shell, and text from the web is data that no later step executes. The run never reads or writes the `mem-auto` or settling status. **Where to look:** every run keeps a folder `<state folder>/research/<id>/runs/<stamp>-<pid>/` (mode 0700, kept 30 days) with each step's brief, stream and files, `events.json` (the web session's queries and URLs), `check.json`, `apply.json`, `report.txt` and `status.json`. When the budget or the time is passed the run stops and reports what it has. `--allow-host` exists for a local test page. **Measured** (stage 1b trial of 2026-11-18, in the plan's Results): no wrong mark in 20 notes, 6 of 12 real notes confirmed, 0.32 USD for 4 runs. The `memory-researcher` agent has no web tools and runs this command for what the memory does not cover (that change to its body is not measured).

## History

A store can keep a git history of its own: `mem history init` makes it a local repository (its `.gitignore` keeps out the `.curation-log` files, `.sources/` downloads, `research/*/data/` and files over 5 MB). `mem` commits at three points only, never per command and never through an agent: when a curation pass ends (`mem curate --done`), at session end (a `SessionEnd` hook, bounded to 5 seconds), and on `mem history commit [-m TEXT]`. `mem history` lists the commits. After `curate --done` commits, curation-log entries older than 30 days are trimmed inside the store (never in a project's `.memory/`, never in a store without git). `mem restore` stays the undo for recent changes; for older ones, git holds the state at each commit point, and states between two commit points older than 30 days are not kept. A remote for backup comes later.

## Use

`mem --help` lists the commands; the `memory` skill holds the recall and writing recipes.

## Tests

```sh
uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q
```

Routing trials (nine headless sessions that cost model usage; they check that each kind of thing to remember lands in the right place, and that a client's name never reaches the store):

```sh
python3 plugins/memory/evals/routing/run_trials.py --claude "$(command -v claude)"
```

Trials keep everything under the ignored `target/` folder at the repository root: their config, data, stores and work folders, so they never read or write a real store or global memories (inherited `MEM_*` and `CLAUDE_PLUGIN_OPTION_*` variables are dropped), and `PATH` entries of an installed copy of a plugin (under `/plugins/cache/`) are dropped so sessions run the `mem` under test. A work folder is kept when a run fails, for inspection. To check the isolation without a model session:

```sh
python3 plugins/memory/evals/routing/run_trials.py --self-check
python3 plugins/memory/evals/recall/run_trials.py --self-check
```
