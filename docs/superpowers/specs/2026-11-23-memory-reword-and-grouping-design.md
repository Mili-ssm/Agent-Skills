# Automatic rewording and a grouped rules block: design

Status: written on 2026-11-23 while the owner was away, under their word of that day to continue with the second plan (C72) and the grouping without assistance; not yet read by the owner. Both parts ship switched off, so the owner decides by turning them on. Open questions are at the end. Extends [the case log design](2026-11-22-memory-case-log-design.md) (C64 to C72) and C46 to C48 of [the capture design](2026-11-21-memory-capture-design.md), whose table reserves the numbers C74 to C85.

Plans: [automatic rewording](../plans/2026-11-23-memory-auto-reword.md), [grouped block](../plans/2026-11-23-memory-rules-grouped.md).

## Part 1: an automatic rewording before the owner (C72)

### Goal

When the present wording of a loaded lesson got worse, the background pass tries one new wording by itself. Only when that one gets worse too, or cannot be written, does the lesson reach the owner. The owner is told, not asked, about a routine rewording, and asked only about what a second attempt did not solve (the owner, 2026-11-22: first an automatic attempt, then one with human feedback).

### State before this change

| Fact | Where |
|---|---|
| A lesson whose present version got worse is listed for the owner at once | `records.got_worse`, `mem curate` |
| The automatic run is: capture, then corroboration, then the fill of missing short forms; capture writes the cases, so the pass runs right after a case arrives | `cmd_auto` in `bin/mem-corroborate`, started by `bin/mem-capture` |
| The fill writes a short form with one session and checks it with a second one, both small models, plus a code check; at most two attempts per wording of a claim | `fill_auto`, `FILL_BRIEF`, `CHECK_BRIEF`, `shortcheck.problems`, `fill-attempts.json` |
| The fill never replaces a short form | `corroborate.fill_candidates` |
| A project record's body holds a line per later sighting, `Seen again (<signal>): "<evidence>"`; a global record's line has the signal only | `bin/mem-capture` |
| A plugin option reaches a background command as `CLAUDE_PLUGIN_OPTION_<NAME>`; it does not reach a `mem` command typed in a session | `plugin.json`, the hooks |

### Decisions

All are the author's proposals, from the owner's ruling quoted in the goal.

| # | Decision | Reason |
|---|---|---|
| C74 | The automatic run gains a third step, `reword`, after the fill. Its candidates are the lessons that load or are cut only by the cap, for which `records.got_worse` holds, whose weight is not `strong`, whose present version was not written by this step, and on which the step did not give up for this version. At most 5 a run, the most failed first | It runs in the same chain that wrote the failed case, so the new wording is in place before the next session starts. A `strong` lesson is the "grave" of C63 and goes to the owner |
| C75 | The step writes from the claim, never from a short form: one session receives, per lesson, the claim, its context, every version with its text and tally, and the signals of the failed cases where the record holds them. It is asked for a different short form of the same claim, under every rule of the fill's brief, that names the situation first and the action concretely | A text rewritten from its own summary loses detail at each pass; the claim is the source (C19). The earlier texts and tallies say what not to repeat |
| C76 | A proposed wording passes the code check and the checking session of the fill, unchanged, and must differ from every text in `versions` (compared without case, spacing and final punctuation). It is not made firmer than the claim: that is the owner's answer (C71) | C60: a lesson influences with measure until it is reinforced. The same two checks passed the gate of C62 |
| C77 | An applied wording is written with `mem memory edit --short ... --reworded`, which adds the version (C66), sets `short_by: model`, so it shows in `mem rules --unread`, and writes `reworded: <today>`. Any other writing of a short form removes `reworded` | The owner is informed through the list of unread short forms. The mark says the present version is the pass's own, so the step does not reword its own rewording |
| C78 | The step tries at most twice for one version. After the second refusal it gives up on that version and writes `reword_failed: <date of the version>`; the lesson then stays listed for the owner. Nothing else changes in the listing rule of C68: a lesson the step reworded is no longer listed because its new version has an empty tally, and one whose reworded version got worse is listed because the step skips it. The row in `mem curate` says which: "no automatic rewording yet", "the automatic rewording of <date> got worse too", or "an automatic rewording could not be written" | The engine cannot see the plugin option from a session, so the rule must not depend on it: with the step off, every lesson that got worse is simply listed, as in 0.7.0 |
| C79 | A plugin option `auto_reword`, off by default. The step runs only with `auto_capture` on and the loaded rules on. Its log line has the key `reword` with `asked`, `written`, `refused_code`, `refused_check`, `same_text`, `gave_up`, `cost` | An automatic change to what loads ships behind a gate (C62 was for C52) |
| C80 | The gate, before the default changes: on a copy of the owner's store the step is run on every loading lesson as if it had got worse. It passes when the checking session accepts at least 80% of the proposals that pass the code check, none equals an earlier text, and the owner, reading the sheet of claim, old and new wording, calls none stronger than its claim. The automatic part is run and recorded in the plan; the owner's reading is the open half | There are no real tallies yet: 0.7.0 began to collect them on 2026-11-23. Forcing every lesson gives a sample now; the real trigger is tested by code |

### Not in this part

| Left out | Why |
|---|---|
| Choosing between the wordings by their tallies, or going back automatically | The owner decides a return (C71); the tallies are too small to compare by code |
| A rewording of the claim | The claim is the lesson; only the owner changes it |
| Evidence quotes from a project record in the brief for a global lesson | They could carry a project's name into a text that loads everywhere |

## Part 2: the rules block grouped by topic

### Goal

The lessons that load are printed under their topic, so related ones sit together and a reader finds the ones that bear on the task (the owner's idea of 2026-11-22). The lessons, their order of choice and their texts do not change: this part changes only how the chosen ones are laid out.

### Decisions

| # | Decision | Reason |
|---|---|---|
| C81 | A plugin option `rules_layout`: `flat` (the default, the block of today) or `grouped`. `mem rules --layout flat|grouped` prints either, whatever the option says | Adopted as the default only after the measure of C84; the owner can look at both |
| C82 | Grouped: the lessons are chosen exactly as today (`rules.choose`, same limits). They are then printed under one heading line per topic, `<topic>:`, the topics in the order of their best-ranked lesson and the lessons inside a topic in their rank; lessons without a topic go under `other:`, last. The heading lines are outside the limit of 2400 characters (at most 16 of them, 25 characters each) | The choice must not depend on the layout, or the two could not be compared |
| C83 | The short forms are not rewritten for the grouped block: each still stands alone | `mem rules --more`, the flat block and a search print them alone. Letting a line lean on its heading is the digest of the third idea, which needs a model and its own gate |
| C84 | The measure before `grouped` becomes the default: the protocol of 2026-11-22 (one small task, a real model, three runs a condition, a hook that prints the block), with the three rules that leave a trace placed among thirteen others, flat against grouped. Grouped is adopted only if it follows the three rules in as many runs as flat | Fix the measure before the change. The protocol is the one the loaded rules were measured with |
| C85 | The digest per topic (a text written by a model from the claims of a topic, checked, with the short forms as fallback) is not built here. It is the plan after this one, and starts from the grouped block | The owner's third idea; it rewrites what loads, so it needs a gate like C80 |

## Checks

| Check | Proves |
|---|---|
| With `auto_reword` off, the pass and `mem curate` behave as in 0.7.0, and the log line has no `reword` key | C79 |
| A lesson that got worse gets a new version from the step; it leaves `mem curate`, shows in `mem rules --unread`, and the step does not touch it again when the new version gets worse, while `mem curate` lists it with "got worse too" | C74, C77, C78 |
| A proposal equal to an earlier text, or refused by either check, is not applied; after two refusals the lesson is listed with "could not be written" | C76, C78 |
| A short form written by hand removes `reworded` | C77 |
| `grouped` and `flat` print the same lessons; the flat block is byte-identical to 0.7.0 | C81, C82 |

## Open questions for the owner

| # | Question | Default taken |
|---|---|---|
| 1 | Turn `auto_reword` on after reading the gate sheet? | Off |
| 2 | Should a `strong` lesson that got worse skip the automatic attempt and come straight to you? | Yes |
| 3 | Make `grouped` the default layout if the measure of C84 passes? | `flat` stays the default; the measure is recorded |
| 4 | Is the digest per topic (C85) still wanted after seeing the grouped block? | Not built |
