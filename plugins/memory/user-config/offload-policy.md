### Offload policy: memory plugin (main conversation only)

These subagents keep memory work out of this context. A single `mem search` or `mem show` you can run yourself stays inline: a dispatch costs this context about 2.5–3k tokens.

| Situation | Delegate to | What it does and returns |
|---|---|---|
| Work resumes (a new session, after a compaction or a long pause), you are about to choose the next task, or the owner asks where things stand, what is pending or what is next. Dispatch it before reading plans or the backlog yourself | `memory:memory-status-checker`, in the background (when the owner asked, wait for its card before answering); ask it follow-up questions with `SendMessage` | Reads git, open-work and plan documents and state memories; returns a status card with a date and source per line, stale written state, and the next steps as the project wrote them. Read-only |
| A question that needs more than one memory search, sources behind the notes, or outside research; a decision that should rest on what is already known | `memory:memory-researcher` | Answers from notes and memories first, researches outside only for what is missing; returns conclusions with references and marks new findings as unchecked (it records them) |
| A task ended with something a later session would need, there is material to mine (a long log, an incident, a debugging session), or the owner says "remember this" about more than one thing | `memory:memory-recorder` | Writes the few memories worth keeping, each in its scope; returns what it recorded |
| The session start text says "Curation due", or the owner asks to review or tidy the memory | `memory:memory-curator`, in the background, without asking first | Reads the curation queue; returns one proposed action per item and applies only the safe subset when asked to apply |
| A topic has many notes and no synthesis, or the owner asks for a compendium or an overview of a subject | `memory:memory-synthesizer` | Writes one indexed synthesis from the topic's notes; returns its parts, the notes left out and the check result |
