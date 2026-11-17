#!/usr/bin/env bash
# PreCompact hook: fixed text for the summary, no interpreter. Exits 0 always.
printf '%s\n' 'Keep in the summary: the path of the active plan file, and every decision, constraint, pitfall or finding of this session that was not yet recorded with mem remember, marked "not yet recorded".'
exit 0
