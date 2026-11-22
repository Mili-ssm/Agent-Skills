#!/usr/bin/env bash
# PreCompact hook: the handoff instruction for the summary, no interpreter (it runs on every compaction, even without
# uv). The text is handoff.INSTRUCTION; a test keeps the two equal. Exits 0 always. With the plugin option auto_capture
# it then starts the background capture (end of this script), which never makes this hook wait or fail.
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
# Automatic capture (option auto_capture, exactly "true"): start mem-capture detached with the hook's JSON on its
# standard input. It waits for the session's own records itself and checks its own limits.
if [ "${CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE:-}" = "true" ]; then
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || here=""
  [ -n "$here" ] && . "$here/find-claude.sh" 2>/dev/null
  type find_claude >/dev/null 2>&1 || find_claude() { :; }
  input=$(cat 2>/dev/null)
  if [ -n "$here" ]; then
    claude="$(find_claude)"
    set -- auto --trigger pre-compact
    [ -n "$claude" ] && set -- "$@" --claude "$claude"
    if command -v setsid >/dev/null 2>&1; then
      (setsid nohup "$here/../bin/mem-capture" "$@" <<<"$input" >/dev/null 2>&1 &) 2>/dev/null
    else
      (nohup "$here/../bin/mem-capture" "$@" <<<"$input" >/dev/null 2>&1 &) 2>/dev/null
    fi
  fi
fi
exit 0
