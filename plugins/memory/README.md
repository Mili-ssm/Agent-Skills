# memory

Notes and memories reachable from every repository and subagent, through the `mem` command.
ADR 0023; see the [stage plan](../../docs/superpowers/plans/2026-11-17-memory-plugin.md).

## Install

`/plugin install memory --marketplace Mili-ssm/Agent-Skills`

## Requirements

[`uv`](https://docs.astral.sh/uv/) on the path. Without it `mem` and the background passes (`mem-auto`, `mem-capture`, `mem-corroborate`, `mem-research`, `mem-settle`, `mem-synthesize`) exit 127, and the session start text says so; no system `python3` is needed (ADR 0035). Every `bin/` file is a small launcher that starts `engine/run.py` through `uv`, so Python caches the compiled engine and one environment serves all of them; with a read-only plugin folder it still works, compiling each time. After a plugin update the first run needs the network once, to build that environment.

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
| Store (notes) | Nothing to set: the default store is created on first use (`mem init`). Or the plugin option `store`, `MEM_STORE`, `--root`. Every entry point resolves it as `--root` > `MEM_STORE` > config file `store` (first line) > the default store, which counts only with its `mem-store.yaml` | A store is read-only unless it holds a `mem-store.yaml` marker; the default one has it. An existing folder of notes without the marker is never made writable by this tool. To sync, make the store a git repository and push it to a remote of your choice |
| Global memories | Plugin option `memories`, or `MEM_MEMORIES`; else `memories/` in a writable store | May not be inside a read-only store. Nothing specific to a project belongs here. `mem terms add <term>` lists a hard term (a write that contains it is refused); `mem terms add <term> --soft` lists a soft one (the agent must ask the owner); `mem terms list` and `remove` manage them |
| Other projects | A local registry, filled as memories are written (`mem projects list`) | Never read by default. `mem search "<q>" --project <name>` or `--all-projects` includes them, each under its own header; the registry holds names and paths, stays on this machine and is not synced |
| Project memories | The main worktree's `.memory/` | Kept out of git through `.git/info/exclude`, added once when the folder is created; remove that line to commit the folder. Memories a repository commits still load, but the owner confirmation in their file does not count and they are marked "from repository" |

## Compaction hooks

| Hook | What it does |
|---|---|
| `PreCompact` | Asks the summary to end with a handoff block: task, state, next step, verified, unverified, plan file |
| `PostCompact` | Reads the block from the summary and checks that the plan file it names exists. Logs one line per compaction to `hooks/log.jsonl` (counts, booleans, field names, the trigger and the session id; no text of the summary and no path). Speaks to the agent in two cases only: no handoff block, or the block names a plan file that does not exist |

`docs/studies/scripts/memory_usage.py` reads these logs.

## Bringing in existing notes

`mem import <folder> [--dry-run] [--overwrite] [--with-sources] [--research-data]` copies the `literature/` and `knowledge/` files, the Markdown files and figures of `research/` (its data and code only with `--research-data`) and the topics of an older folder of notes into the store, reading the source only. Files that differ stay as they are and are listed, unless `--overwrite`; imported text is not checked for secrets or terms, only reported.

Plugin options take effect in the next session: a `SessionStart` hook exports them to shell commands and writes them under `$XDG_CONFIG_HOME/agent-memory/` (else `~/.config/agent-memory/`). Those files (`store`, `memories`) are yours to edit: the hook records what it wrote in `<name>.hook` and only updates or removes a file whose content matches that record, so a file you wrote or changed stays, and with no `store` option the hooks hand over the store that file names, else the default store.

## Syntheses

A synthesis is the long version behind a group of notes: one indexed document per subject with origins, reasons, and when a thing applies and when not. `mem synthesis new|add|append|edit|attach|list` build it one cited part at a time; `rename`, `remove` and `detach` change a part or a note's link, and `topics` sets the synthesis's topics, `refs` adds or removes inline note references from a file of `section | unit | add|remove target` lines without retyping any text (`mem restore s:<handle>` undoes a step); `integrate FILE` joins loose knowledge notes to parts from `note | s:<handle>#<section> | append|unit N | fingerprint` lines (an appended sentence is the note's own claim with its reference, never other text; the secret and forbidden-term checks always apply; all rows of a file are one logged group, undone by `mem restore s:<handle>` while it is the newest change, and a row whose part changed since it was read is refused), and `integrate --candidates` prints as JSON the notes each synthesis could take with its parts and their units; a note says which part it recalls (`part of:`), and `mem search` prints matching parts after the notes. Notes are written loose; a curation pass (`mem curate --notes`) joins them to a synthesis, lists notes to unify (`mem unify`) and topics that have enough notes for one. The `memory-synthesis` skill holds the procedure. The `memory-research-wave` skill guides a study across several sources or agents (leads, writers from full text, fresh-context fact-checks, one fixer, review, a lesson with the wave's figures) and points to the note-writing rules in the `memory` skill. `mem-synthesize --backfill [s:<handle> ...]` adds the references to syntheses that have none: one read-only Haiku session per synthesis (Read only, no shell, web or write) proposes which source note supports each sentence and code applies them with `mem synthesis refs`; `--dry-run` lists the parts and the estimated cost, and a part already done and unchanged is not sent again. Writing a synthesis with `mem-synthesize` ends with the same step (about 0.05 USD each; a failure there leaves the synthesis as it is and does not fail the topic; `--no-references` skips it).

A project can also keep stamped syntheses in `.memory/syntheses/` (`organization`, `plans`, `pending`, `conventions`): each `## ` part ends with the files it covers and the commit it was written at. `mem project-synthesis add <name> "<heading>" --paths a,b --body-file F` writes or replaces a part, `confirm p:<name>#<handle>` re-stamps it after you checked it, `list` shows each part's freshness, and `mem show p:<name>[#<handle>]` reads it, marking a part whose files changed since as possibly stale. They need no store and never write to one.

## Subagents

They keep the main conversation's context on the task. To have the main model delegate to them, the plugin's `SessionStart` hook prints [`user-config/offload-policy.md`](user-config/offload-policy.md) at session start, after `/clear` and after a compaction (implemented, ADR 0032; no eval covers this table's delivery yet): one row per subagent with when to delegate, the call and what comes back. The hook is silent when the option `offload_table` is `false` (`/plugin configure memory@mili-ssm`) and when `~/.claude/CLAUDE.md` already holds the table's heading; turn the option off if the table reaches the session another way (an `@import`, a project `CLAUDE.md`, account instructions), or it loads twice. Copilot CLI and Codex users, and users who prefer the pasted copy, paste it into their user-level instructions file. With agent-skills installed, paste it right below that plugin's offload block, between the same kind of markers (`<!-- Pasted unchanged from Agent-Skills plugins/memory/user-config/offload-policy.md at <commit> -->` … `<!-- End of memory offload-policy.md -->`), and paste it again after an update that changes it. A table in the system prompt is what made delegation reliable for agent-skills (ADR 0010); descriptions alone did not.

| Subagent | Given | Does | Returns |
|---|---|---|---|
| `memory-researcher` (Haiku) | A question | Answers from the memory, deeper sources if needed, outside research only for what is missing, which it records as findings | Conclusions with their references, and what is new and unchecked |
| `memory-recorder` (Sonnet) | An account of what happened, or logs and files | Writes the few memories worth keeping, each in its scope; optionally lists the curation queue | What it recorded |
| `memory-curator` (Haiku) | Nothing | Reads the curation queue | A table of proposed actions; asked to apply, it applies only the guarded safe subset (`mem curate apply --safe`) |
| `memory-synthesizer` (Haiku) | A topic and a slug | Writes one synthesis from the topic's notes, only through `mem synthesis`; stops when the topic has too few notes | Parts, notes left out, `mem check` result and the notes to attach |
| `memory-status-checker` (Haiku) | Optionally a task or topic | Reads git, the open-work and plan documents, state memories and project syntheses; checks the written state against git since it was written | A status card with a source per line, drift (stale memories included, changed by none), next steps as written; answers follow-up questions (`SendMessage`) from what it read |

The start text every other subagent receives is not given to these five: they carry their own instructions.

## Curation

`mem curate` lists what needs a decision (memories that say the same or the opposite, expired ones, ones seen several times, ones nobody confirmed, established lessons whose short form the automatic fill will not write: it gave up, or the lesson is repository-tracked, or a strong project lesson not confirmed by the owner); `mem merge`, `refute`, `distinct`, `supersede`, `forget`, `confirm` and `promote` carry a decision out, and `mem restore` undoes the last one on a memory. Records change only through commands, never by editing files: `mem note edit` corrects a note (claim, topics or one section) and `mem memory edit` a memory (`mem restore` a retired one first). `mem note confirm` adds a source-backed line to a note's evidence and `mem note dispute` marks the note `[disputed]` (a claim a source contradicts: check it before relying on it; `--clear` removes the mark); a memory marked `web, unconfirmed` is a web finding no second source has confirmed. Nothing is deleted. The session start text says when a pass is due: `Curation due: N items (2 same or opposite, 1 expired) (after the current task: dispatch memory:memory-curator).`

It counts the decision items (written again after being refuted, same or opposite, newer state, expired, seen often, not confirmed in 90 days, established lesson whose short form the automatic fill will not write) that the last `mem curate --done` did not list; new memories alone do not count, and the line is absent at 0. `at least N` means the count is incomplete: the start-time pair search used up its budget (150,000 comparisons over both folders), or one folder's count failed.

`--done` records the listed items in `curated-items.json` in the data folder and prints `recorded K items (<scope>)`. If `curated-items.json` exists and cannot be read, `--done` exits 2 and writes nothing; a malformed one is replaced.

The queue's categories: pairs of the same project's state memories are listed apart as `newer state of the same project?`, to be settled with `mem supersede <old> <new>` or `mem distinct`; project memories seen 3 times or more are candidates for a global lesson (`mem promote <h>`). The `memory-curation` skill holds the procedure and the `memory-curator` subagent proposes actions and applies only the guarded safe subset when asked to apply.

## Automatic curation (off by default)

Plugin option `auto_curation` (exactly `true` turns it on; any other value is off). **What starts it:** the `SessionEnd` hook starts one detached wrapper that runs `mem history commit`, then `bin/mem-auto run` (the claude binary is `CLAUDE_CODE_EXECPATH`, `claude` on `PATH`, or the hook's parent process; the wrapper outlives the session). The run counts the global memories and notes written since the last run ended (so its own edits do not count) or the last curation pass (`mem curate --new-since`; an edit counts) and goes on only when the count reaches `auto_curation_threshold` (default 10); right after a run the count is 0.

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

Plugin option `auto_settle` (exactly `true` turns it on) and `auto_settle_minutes` (least time between runs, default 30). **What starts it:** the `SessionStart` hook exports `MEM_SETTLE_AUTO`, `MEM_SETTLE_MINUTES` and `MEM_SETTLE_CLAUDE` (the claude binary) to the session's shell commands and creates the settle state, so the first write is not taken as already judged. A `mem remember` or `mem memory edit` of a global memory then checks `mem settle due` (one state file) and, when it is due, starts `bin/mem-settle run` detached; the write is never delayed or failed by it. Without those variables nothing starts, so trials and tests never trigger it; records written with `--origin pipeline` never trigger. The same detached `SessionEnd` wrapper starts `bin/mem-settle run --minutes 0` for what is left, after the history commit and beside `mem-auto`.

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

**What it does:** after an automatic capture that wrote something, `bin/mem-corroborate` runs in the background. It shows a small model the lessons of every registered project and the global ones (memories a repository tracks in git are left out) as lines with opaque ids, and applies only what two sessions agree on:

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
| Case log (implemented, 0.7.0) | Each lesson keeps a `log` of dated cases (`worked`, `failed` or `seen`, from the capture signal) and its `versions` with a tally each; `mem show` prints them. A loaded lesson with a failed case after it loaded is named by `mem rules`, listed by `mem curate` under "balance got worse after loading" and counted in the session start text; it keeps loading until the owner decides: reword (`mem memory edit <h> --short`), drop (`mem forget <h>`) or `mem triage accept <h>` to keep the wording. `mem confirm` and `mem remember` take `--outcome` and `--seen-on`. Rules: [design](../../docs/superpowers/specs/2026-11-22-memory-case-log-design.md) |
| Wording | A lesson is reworded once, when its global record is written; later evidence only adds sightings |
| What counts as a project | A registered project whose folder exists, holds a memory folder and is not under a temporary folder; it is known by a hash of its path, so a moved folder or a second clone counts as another project |
| Cost | Two model sessions per pass, each within `auto_capture_budget`; no pass when no lesson changed; after two passes that fail on the same lessons it stops until one changes |
| Undo | `mem-corroborate undo <stamp>` restores every file a pass changed; `<stamp>` is a folder name under `<data folder>/corroborate/runs/`. It refuses, changing nothing, when one of those files was edited since |
| Lapse | An unconfirmed lesson gets an end date 30 days after its last sighting; a new sighting within 60 days after that date revives it. A lapsed lesson stays stored and in quarantine; `mem memories --global --quarantine` still lists it |
| What is sent to the model | The claim and context of every lesson of origin `transcript`, from every registered project and the global folder, except memories a repository tracks in git; no transcript text and no project name beyond what a lesson's own text says |

**Where to look:** `<data folder>/corroborate/` holds `status.json`, `log.jsonl` (counts only), `seen.json` and `runs/` (private: it holds lesson text). `mem-corroborate run --dry-run --out FILE` runs both model sessions (up to `--budget` each, default 0.25 USD), writes what a pass would do to FILE and changes no record. After a failed pass the session start text carries one line, `memory: the last corroboration pass failed (<reason>)`, until `mem-corroborate ack`; `mem-corroborate status` shows the last run.

**Evidence and limits:** on a private copy of real records (36 lessons, 3 projects), 6 of 7 dry runs gave a usable answer (the seventh used line numbers as ids, was refused by code, and the brief was corrected; 3 of 3 after that); the 6 proposed the same 15 groups; a run applied 12 to 15 of them, every refusal for an unfaithful rewording; the owner accepted 15 of 15. Not measured: use over time, lessons of more than one project, and whether a released lesson stops a failure from recurring. Only records of origin `transcript` are read: a global memory written by hand is never merged or given sightings.

### Capture trial (`mem-capture run`; writes to the store only with `--write`)

`mem-capture run --transcript PATH --out FILE [--project DIR] [--since-line N] [--model NAME] [--budget USD] [--write]` reduces one session transcript to an extract and has one headless session (no Bash, no hooks) propose memory candidates; a program keeps only those whose evidence is copied from the transcript. The result file (mode 0600) holds the kept and dropped candidates, the cost and the line range; it holds session text, so keep it private: `--out` must be outside any repository (a folder with a `.git` entry in it or above is refused) and must not be a symlink. Defaults: model `haiku`, budget 0.25 USD per run (`--budget`); the work folder is temporary and removed at the end (`--keep-work` keeps it). `recorded.txt` gives the session the live claims of the project and of the global scope. With `--write`, code (never the model, which has no Bash) records each kept candidate through `mem`, so every check `mem` makes at writing applies; it writes in the project scope only, never the global one. A record starts `from transcript, unconfirmed`, with `reach` and `weight` set, and becomes established when distinct sessions have shown it (light 1, medium 2, strong 3); a candidate that names an existing record, or repeats its claim, adds this session as one more sighting, and one session counts at most once however often the command runs. An unconfirmed record lapses 30 days after the last session that showed it. The result file gains `written` (per candidate: `remembered`, `sighting` or `skipped`, with the reason); a failure on one candidate never stops the others or changes the exit code. Without `--write` nothing is written to the memory store. No hook runs `run`; with `auto_capture` on, the hooks start `mem-capture auto`, which runs the same steps per window with `--write` (section above).

## Loaded rules (a lesson loads once it has a short form)

**What it does:** an established lesson that has a short form loads as one line of the session start text, so an agent that never searches still sees it. The text is built by code from the records at each session start; no model rewrites the list. `mem rules` prints the same block, or `No rules loaded.` when none loads. The plugin option `loaded_rules` (on by default) switches the whole feature off; `--no-load` switches one rule off.

**How a short form comes to exist** (implemented; the automatic fill passed a small gate on 2026-11-22, see the limits below):

| Path | Who writes it | Marked | Loads |
| --- | --- | --- | --- |
| Automatic fill, when `auto_capture` is on and `loaded_rules` is not off | A small-model session, after the matching pass of `mem-corroborate auto` | `short_by: model` (unread) | At the next session start, before anyone read it |
| `mem memory edit <h> --short TEXT`, `mem remember --short TEXT` | You or an agent; code checks the text against the claim | `short_by: model` | Same |
| The same with `--user-read` | The owner, who read the text; no check | No mark | Same |
| `fill --dry-run` then `fill --items FILE` | A model proposes, the owner reads the file | No mark | Same |

**The automatic fill:** for established lessons that have no valid short form, one session writes the short form and the topic (a lesson that already has a short form is never touched, even without a topic); code refuses a short form that drops its claim's hedge, adds an absolute word, holds a link or says "owner" (`engine/memories/model.py`); a second session checks the survivors against their claims; what passes is stored. The pass never changes `load`. It runs at every `mem-corroborate auto`, after the matching pass and whatever that pass did, in the background, under the store run lock; `mem-corroborate status` prints a `last fill:` line (counts only) when the last fill wrote, refused, held or stopped.

| Rule of the fill | Value |
| --- | --- |
| Attempts | At most two per wording of a claim. A wording once tried is not written again by the pass: a short form you undid or removed stays away until the claim changes |
| After the second refusal | A general lesson is held at triage with the reason (`mem triage hold <h> --because TEXT` does the same by hand); a project lesson stays without a short form |
| Failed session | Counts no attempt; after three in a row the step waits until the lessons change |
| A `strong` project lesson | Not filled until the owner confirmed it (`mem confirm <h> --by-owner`) |
| A general lesson at its first establishment | Waits at triage only when its weight is `strong`; `light` and `medium` are released and may load once they have a short form |

**The automatic rewording (off by default; its gate passed):** plugin option `auto_reword` (exactly `true` turns it on; it needs `auto_capture` on and `loaded_rules` not off). When a loaded lesson got worse, the background pass, after the fill, rewords its short form from the claim, once for each wording the owner wrote or read (at most 5 a run, two tries per wording): code and the checking session test the new text as they test a first short form, and nothing is written when either refuses it or when it equals an earlier text. A reworded lesson shows in `mem rules --unread`. The pass never rewords its own rewording, nor a wording the owner kept (`mem triage accept`): when one of those gets worse the decision stays with the owner. A wording the owner writes afterwards gets one automatic attempt again. A `strong` lesson is reworded like any other. `mem-corroborate reword [--every] [--limit N] [--dry-run] [--sheet FILE] [--budget USD]` runs the step by hand; `--every` takes loaded lessons that did not get worse too (at most `--limit`, 30 by default) and is refused without `--dry-run`, `--dry-run` runs both model sessions and changes no record, and `--sheet FILE` (outside any repository: it holds lesson text) writes a table of each candidate and its outcome. **Gate:** the automatic half ran once on a copy of one store, with every loaded global lesson taken as a candidate, and passed; the owner read the sheet on 2026-11-23, called no proposal stronger than its claim, and turned the option on in their own configuration; the default stays off. Figures and limits: [the plan results](../../docs/superpowers/plans/2026-11-23-memory-auto-reword.md#results) (design: C74 to C80 of [the design](../../docs/superpowers/specs/2026-11-23-memory-reword-and-grouping-design.md)).

### The digest per topic

Released in 0.9.0 (2026-11-23); off by default (`rules_layout` unset is `flat`). Rules and the reasons are in [the design](../../docs/superpowers/specs/2026-11-23-memory-topic-digest-design.md) (C86 to C97).

| Item | What it is |
|---|---|
| Layout `digest` | Plugin option `rules_layout: digest` or `mem rules --layout digest`. Prints the grouped block with, per topic, a heading that says when it applies and, for each global lesson, a line written for that heading; project lessons keep their short forms |
| Fallback | A text prints only while its fingerprint matches what it was written from (the claim, the context, the topic's lessons); otherwise the short form (line) or the bare topic (heading) prints. A missing, broken or stale `rules-digest.json` in the data folder gives the grouped block. Session start never calls a model |
| The index line | Names what each topic is about when it has a fresh heading, else the topic alone |
| Limits | No limit of number; 3200 characters of rule lines and 1600 of index line |
| Step | `mem-corroborate digest [--dry-run] [--sheet FILE]` (also `--claude`, `--budget`): one session writes the headings and lines, code checks them as it checks a short form, a second session checks each line against its claim, then `rules-digest.json` is written in the data folder. It writes no lesson record, so there is nothing to undo. `--dry-run` runs both sessions and writes no file; `--sheet FILE` (outside any repository: it holds lesson text) writes a table of each line and its outcome |
| Automatic run | After the fill and the rewording, when `rules_layout` is `digest`, `auto_capture` is on and `loaded_rules` is not off |
| Gate | Automatic half passed on 2026-11-23, on a copy of a real store: 4 topics, 4 of 4 headings and 8 or 9 of 9 lines accepted (89% and 100% on two runs), none refused by code, 0.01 USD a run; the block was 2501 characters grouped and 2696 digest ([results](../../docs/superpowers/plans/2026-11-23-memory-topic-digest.md#results)). The owner read the sheet on 2026-11-23, called no line stronger than its claim, and turned `rules_layout: digest` on in their own configuration; the default stays `flat`. Noted in that reading: one line named an example its claim does not, and one heading joined two unrelated situations of a topic |

**Reading what loaded unread:** `mem rules --unread` lists the short forms a model wrote, with their claims; `mem rules --read <h>...` or `--read all` marks them read (the owner's act); `mem curate` prints `short forms nobody read: <N> (mem rules --unread)`. Change one with `mem memory edit <h> --short TEXT` (the mark stays), turn it off with `--no-load`, or switch every rule off with the option `loaded_rules`.

```
memory: lessons learned in earlier sessions. Apply them with judgment: follow one unless you have a reason not to, and mention a skipped one only when it matters to the user.
- Invented rule 1 (the user vouched for it)
- Invented rule 2 (held in 2 projects)
3 more lessons by topic: testing 2, process 1 (mem rules --more <topic>, when a topic fits your task)
```

| Term | Meaning |
| --- | --- |
| Loaded rule | A lesson's short form followed by its standing, `(held in N projects)` for a global lesson, `(held in N sessions)` for a project one, `(the user vouched for it)`. The standing is computed from the record, never written by a model |
| Short form | One line of at most 120 characters, kept in the record (`--short`), checked by code against the claim (hedge kept, no absolute word added, no link, no "owner"); a model's is marked unread until `mem rules --read` |
| Topic | One or two lowercase words of at most 24 characters (`--topic`), used to group what did not load |
| Index line | The line after the rules: how many more lessons there are, by topic, ending with `(mem rules --more <topic>, when a topic fits your task)`. At most 1600 characters |
| Load state | Absent: the lesson competes for a place. `index` (`--index-only`): never among the rules, counted in the index line. `no` (`--no-load`): nowhere. `--load` removes the field |

**What loads:** a lesson of origin `transcript` that is live, established (not in quarantine), has a valid short form and is not `no` or `index`. A global lesson must also be past triage (`mem triage accept <h>`) or confirmed by the owner; a project lesson needs two sessions or the owner's confirmation. No limit on the number of rules, at most 3200 characters of rule lines. A project lesson that was generalized never loads twice: when its global twin can itself load and competes for a place, only the twin loads; when the twin awaits triage, has no short form, is index only or is off, the project lesson loads in its own project.

**Order:** confirmed by the owner first, then weight (`strong`, `medium`, `light`), then the number of projects that saw it, then of sessions, then the latest sighting, then the handle. The three best project lessons get the first places. A lesson that does not fit stops the line: nothing ranked lower jumps ahead of it.

**What never loads:** a lesson in quarantine; a lesson with no short form (not in the index line, unless it is index only: that line counts an index-only lesson with or without one; the session start text counts it once, under "Curation due", when the automatic fill will not write its short form, and `mem rules --more` ends with how many lessons lack one); a lesson that awaits triage (the `Triage:` line announces it; `mem rules --more` lists it as "awaits triage"); a project lesson seen in one session and not confirmed; a lesson with load state `no`.

**The index line** counts the lessons that qualify and did not fit, plus the index-only ones. A lesson with no topic is counted as `other`, which is why `other` is refused as a topic; when no left-out lesson has a topic the line reads `N more lessons: mem rules --more`.

| Command | Use |
| --- | --- |
| `mem rules` | The rules block and the index line, as the session start prints them |
| `mem rules --more` | Every lesson left out, grouped by topic, with the reason (over the limit, index only, awaits triage) and its standing, ending with `mem show m:<handle> prints a whole lesson.` |
| `mem rules --more <topic>` | Only that group (`other`: lessons with no topic) |
| `mem remember ... --short TEXT --topic TEXT` | Write a lesson with its short form and topic |
| `mem memory edit <h> [--global] --short TEXT --topic TEXT` | Set or change them; an empty text removes one. The short form is checked by code and marked unread; `--user-read` (the owner read it) skips the check and the mark. Same flag on `mem remember` |
| `mem rules --unread` / `mem rules --read <h>... \| all` | List the short forms nobody read, with their claims / mark them read |
| `mem triage hold <h> --because TEXT` | Put a general lesson back at triage with a reason (one line, at most 200 characters); it stops loading |
| `mem memory edit <h> [--global] --no-load` | Turn one rule off; the lesson stays stored and searchable |
| Plugin option `loaded_rules` (default on) | Set it to `false` to switch the whole feature off: the session start text carries no rules block and no index line. `mem rules` still prints what would load, after a first line saying the feature is off |
| Plugin option `rules_layout` (`flat` default, `grouped`, `digest`) / `mem rules --layout flat\|grouped\|digest` | `flat` prints one list in rank order. `grouped` prints the same lessons, in the same rank, under a `<topic>:` line each: topics in the order of their first lesson, lessons with no topic under `other:` last. `digest` is `grouped` with a situation after the topic (`<topic>: <when this applies>`) and a line for a global lesson written for that heading, where the digest file holds a fresh one (see [the digest per topic](#the-digest-per-topic)). The choice changes only the text; which lessons load is the same. **Not measured:** two attempts to compare the two on a real model stopped on runs voided by permission denials (the model chains its commands in one call), so no figure exists and `flat` stays the default; the change of default is the owner's ([trial and why it stopped](evals/rules_layout/README.md)) |
| `mem memory edit <h> [--global] --index-only` | Keep it out of the rules but counted by topic in the index line |
| `mem memory edit <h> [--global] --load` | Remove `--no-load` or `--index-only` |
| `mem-corroborate fill --dry-run --out FILE` | One model session proposes a short form and a topic for up to 30 lessons that qualify and lack either (the brief tells the model to keep the claim's hedge and, when the claim is too long, to drop alternatives and detail first, never the hedge; a lesson with a short form and no topic gets both proposed, and applying the file replaces its short form); the file also carries each lesson's load state, copied from the record, for the owner to set; changes no record |
| `mem-corroborate fill --items FILE` | Apply the file as you left it; starts no model session |

**Giving lessons a short form:** the owner runs `fill --dry-run --out FILE` (the file must not be inside a repository: it holds lesson text), reads it, then runs `fill --items FILE`. Each item holds `id`, `handle`, `scope`, `claim`, `short`, `topic`, `claim_digest` and `load` (`yes`, `index` or `no`). Edit `short`, `topic` and `load`, or delete an item to skip that lesson. An item is dropped when its handle or scope does not match its id, or its record cannot load; it fails when the claim changed since the file was made. A proposal that is not valid (a short form of more than 120 characters, a bad topic) or missing stays in the file with a `problem` field saying why: shorten or fix it, then apply; `fill --items` ignores `problem` and drops an item that is still invalid. `mem-corroborate undo <stamp>` (printed by `fill --items`) puts every written record back while its run folder exists; a later pass may prune old run folders.

**Changing or removing one rule:** reword it with `mem memory edit <h> --short TEXT` (checked, marked unread); turn it off with `--no-load` (the option `loaded_rules` switches all of them off). Editing a claim removes the short form, so reword with `--claim` then `--short`.

**Limits:**

| Limit | Why it stays |
| --- | --- |
| A short form written by the pass loads before anyone read it | Code and a second session check it, not a person; read it with `mem rules --unread`, switch it off with `--no-load` or `loaded_rules` |
| A `strong` lesson and a lesson refused twice wait for the owner | Triage for a general one, `mem confirm --by-owner` for a project one |
| A project lesson seen in one session never loads | Not established: it needs two sessions or the owner's confirmation |
| A rule may repeat what the owner's own instruction files say | Turn it off with `--no-load` |
| Rules do not reach subagents | The session start hook runs in the main session only |
| `mem-corroborate undo` of a `fill` run works only while its run folder exists | A later corroboration pass prunes old run folders |
| An unexpected error in the middle of `fill --items` stops it with exit 1 and no summary line; the edits already made are kept and can be undone | Each edit is journaled before the next; the count is printed only at the end |
| The checks catch a dropped hedge, an absolute word, a link, "owner", and what a second session judges unfaithful; they do not prove a short form is no stronger than its claim | A gate on a private copy of a real store, run twice on 2026-11-22 ([results](../../docs/superpowers/plans/2026-11-22-memory-auto-short-forms.md#results)): on its second run the code check refused none of 11 short forms the owner called faithful, the checker passed 10 and 11 of them, and code and checker together refused 30 of 30 forms made stronger on purpose. It also showed the gap: a short form that keeps its hedge but loses the situation its claim is about passed every check. Eleven labels can catch a bad checker and cannot prove a good one |
| Every loaded rule gets the same space, not more by weight | There is no limit of number now, only 3200 characters of rule lines |
| With no `store` option set, the hook uses the default store | As for the rest of the session start text |
| The session start text grows by up to about 5000 characters when the rules and the index line fill their limits | The limits above (174 for the header, 3200 for the rules, 1600 for the index line) |
| Whether a loaded lesson stops its failure from recurring is read by hand from the capture log | No date on each sighting yet |

**Evidence:** one small task, three runs a condition, a real model, with the rules printed by a throwaway hook, not by this plugin. With no rules, none of three checkable practices was followed (0 of 3 each); with three rules in the session start text, all three in 3 of 3 runs; with the same three among twelve unrelated rules, again 3 of 3, at about 7% more cost than with no rules ([measurement](../../docs/superpowers/plans/2026-11-22-memory-loaded-rules-and-reminders.md#measurement-loaded-rules-are-followed-2026-11-22)). Not measured: a rule that conflicts with another instruction, a long session, and several rules at once in real work. On a private copy of 15 real lessons the small model proposed 13 short forms and 2 passed 120 characters (then dropped; now kept in the file marked with a problem); the owner's reading of them is pending. With this plugin and five of those rules loaded, three runs on one task showed no measurable effect and no harm (the model stated its reading of an ambiguous term in 2 of 3 runs with the rules and in 2 of 3 without); so the evidence that rules are followed is the first measurement, not a run of this plugin. **Measured once, on one store:** in the gate's fill runs on a private copy the automatic fill wrote 14, then 13, of 15 short forms, and the owner read them all and asked for one to be reworded in the first run and none in the second. **Not measured:** how often it wrongly accepts or refuses on other lessons, and a run from an installed copy of the plugin.

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

## Session start lines about the store

Besides the rules and the curation lines above, the session start text adds up to two lines about the store, each only when its count is above zero (singular: `1 changed note`, `1 note is past its review date`).

| Line | Means | Do |
|---|---|---|
| `History: N changed notes held back from the last commit: run mem check.` | The last history commit left out notes that fail `mem check` | Run `mem check` and fix what it reports; the next commit takes the note |
| `Re-read due: N notes are past their review date: mem review.` | Notes due for re-testing (llm knowledge) plus notes due for re-reading (web literature), as `mem review` lists them; refreshed once a day | Run `mem review`, then re-read or re-test the notes that touch the task |

## History

A store can keep a git history of its own: `mem history init` makes it a local repository (its `.gitignore` keeps out the `.curation-log` files, `.sources/` downloads, `research/*/data/` and files over 5 MB). `mem` commits at three points only, never per command and never through an agent:

| Point | When | Held back |
|---|---|---|
| Curation | `mem curate --done` ends a pass | A changed note that fails `mem check` |
| Session end | A `SessionEnd` hook starts a detached wrapper that runs `mem history commit` (bounded to 30 seconds) after the hook returns, then the automatic runs | Same |
| By hand | `mem history commit [-m TEXT]` | Same |

A held-back note is not committed: the other notes are, and it stays in the working tree. `.git/mem-held-back` lists the notes that fail `mem check` (written after the check, in one step), and `mem history commit` prints `held back: <path>` on stderr for them when the commit did not fail; the next commit takes a note once `mem check` passes. A note edited while the check ran is left for the next commit without being listed. The session start lines are in the table above. `mem history` lists the commits. After `curate --done` commits, curation-log entries older than 30 days are trimmed inside the store (never in a project's `.memory/`, never in a store without git). `mem restore` stays the undo for recent changes; for older ones, git holds the state at each commit point, and states between two commit points older than 30 days are not kept. A remote for backup comes later.

## Use

`mem --help` lists the commands; the `memory` skill holds the recall and writing recipes.

## Tests

```sh
uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto
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
