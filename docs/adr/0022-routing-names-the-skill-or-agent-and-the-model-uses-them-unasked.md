# 0022 Routing rows name the skill or agent, and the model uses them unasked

Status: accepted · Date: 2026-11-15 · Amends 0007

## Context

The owner said on 2026-11-15: "I don't usually ask for skills explicitly; I would like the model to use them automatically", perhaps not all of them.

Observed in the owner's 62 sessions (2026-10-27 to 2026-11-15, a snapshot): no plugin command was ever typed; all 262 dispatches of the ten specialist agents and all 35 loads of this plugin's skills were started by the model. Four knowledge skills were never loaded: `api-design`, `observability`, `qa-principles`, `security-principles`.

`user-config/routing.md` named a slash command in 8 of its 14 rows, first in 6, and said "run them when the need appears", yet all 14 commands set `disable-model-invocation: true`. `implementer` writes most of the code and has no Skill tool, so a skill's rules reach delegated code only through its brief. ADR 0007 treats auto-triggering as "a bonus, not a requirement". Three rules lived only in the owner's user-level file, against ADR 0021.

## Decision

- New requirement R6: the model loads this plugin's skills and dispatches its agents when the task matches, without the owner naming them.
- `routing.md` opens with that rule, and each row names the skill or agent the model can use. One sentence says the slash commands are the owner's manual entry.
- Narrower triggers: `intent-elicitation` only while the intent is unclear and Superpowers `brainstorming` only while the design is open, because they interview the owner; `feature-briefing` only when a plan needs evidence from several sources; `architect` and `security-reviewer`, the costliest agents, for work that spans several modules or a design, plan or security surface under review. `pre-mortem`, also on Opus, keeps its own row in the offload policy.
- A skill is for work the main conversation does itself; a specialist agent is for an assessment that needs a fresh context.
- Bounds proposed with this record, not set by the owner: no skill or agent for a question answerable from what was already read, nor for an edit under ~20 lines that touches no contract, schema or input handling. The bounds apply to the knowledge skills and the specialists, not to the offload policy or the review rows.
- Before briefing `implementer` on work a knowledge skill covers, the main conversation loads the skill and puts the rules that apply into the brief.
- Ported from the owner's file: the full project assessment row, `prompt-engineer` as the reviewer of prompts, and the questions a narrow review and a process review ask. The `fixer` row also covers tests broken by a rename or refactor.
- No description changes, so no eval is due (N6).

## Alternatives

| Option | Rejected because |
|---|---|
| "Use proactively" in the specialists' descriptions | They are already dispatched unasked; a description change must be measured, and ADR 0007 found that wording over-delegates |
| Remove the 14 commands | Not decided by the owner; an open question in `docs/requirements.md`. N8 is unchanged |
| Give `implementer` the Skill tool | Changes a worker that the offload evals measure, and loads skill text into every run |
| Keep the rule in the owner's file | ADR 0021: rules live in `user-config/` |

## Consequences

- `routing.md` grows by about 1,600 characters; the owner's personal text shrinks by about as much once re-pasted.
- The rule ships unmeasured and reaches the Copilot and Codex ports.
- More unasked loads and dispatches are expected; the narrower triggers and the two bounds limit the costly ones.

## Revisit if

The owner starts typing commands again, or a platform change lets a subagent load skills.

### Kill criteria

Proposed with this record; the owner has not set them.

| Signal | Action |
|---|---|
| `architect` or `security-reviewer` dispatched for a change under ~20 lines, in 2 traces | Narrow the specialist row |
| Over 10 sessions, specialist dispatches exceed 6 per session (4.2 in the 62 sessions measured) | Narrow the specialist row |
| Over 10 sessions, loads of this plugin's skills exceed 1.2 per session (0.56 measured) with no better result | Narrow the knowledge-skill row |
| A skill that interviews the owner starts on a task whose intent was clear, in 2 traces | Tighten its row |
| After 10 multi-task sessions, the four unused knowledge skills are still never loaded before a matching brief | Move the brief rule into the offload policy, which needs its evals |

## Review 2026-11-15

The owner reviewed the 14 commands the same day and decided:

- The commands stay as they are, as the owner's manual entry, although none was typed in 62 sessions. They cost no context, and removing them would change `validate.py` and `port.py`. The text of N8 is unchanged; its "Reopen when" cell records this decision.
- Two rules lived only in the commands, so they never applied to a dispatch the model started. Both move into the specialist row of `routing.md`: every finding of a specialist is relayed, none dropped, in the owner's reply format, followed by the decisions it leaves to the owner; and `doc-curator`, `qa-engineer` and `performance-analyst` run in their read-only mode unless the owner asked for the edit.
- `prompt-engineer` reviews a changed prompt, skill, agent definition or CLAUDE.md even when it is one file. This was the last rule that lived only in the owner's user-level file.

Kill criterion, proposed with this note: a specialist's finding missing from the reply, or an edit mode started without the owner's request, in 2 traces → restate the rule in the offload policy, which needs its evals.
