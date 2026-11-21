#!/usr/bin/env bash
# PreCompact hook: the handoff instruction for the summary, no interpreter (it runs on every compaction, even without
# uv). The text is handoff.INSTRUCTION; a test keeps the two equal. Exits 0 always.
cat <<'TXT'
End the summary with this block, one line per field, so the next context resumes from it:
HANDOFF
task: <the task in progress, in one sentence>
state: <what is done>
next: <the next step>
verified: <what a check or the owner confirmed>
unverified: <what is claimed but not checked>
plan: <path of the active plan file, or "no plan">
Before the block, list every decision, constraint, pitfall or finding of this session that was not yet recorded with mem remember, one per line, each line starting with "not yet recorded:", so that the next context can record them.
TXT
exit 0
