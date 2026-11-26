#!/usr/bin/env bash
# PostCompact hook: `mem` checks the handoff block of the summary and prints the lines that tell the agent what
# is missing (nothing when the block is complete), and logs counts only. The hook's JSON on standard input goes to
# `mem`. Hook processes do not get the variables that session-env.sh exports, so the options are passed on here.
# Silent and always exit 0, also when uv or mem fail: a failing hook would disturb every compaction.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || exit 0
. "$here/store-env.sh" 2>/dev/null; type export_store_env >/dev/null 2>&1 && export_store_env
if command -v timeout >/dev/null 2>&1; then
  timeout 4 "$here/../bin/mem" compact-log --hook 2>/dev/null || true
else
  "$here/../bin/mem" compact-log --hook 2>/dev/null || true
fi
exit 0
