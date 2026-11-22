#!/usr/bin/env bash
# SessionEnd hook: commits what changed in the store, when the store is a git repository (`mem history init`).
# Options are passed on as in session-index.sh. Bounded by `timeout 5`, silent, always exit 0: a failing hook
# must never disturb the end of a session. mem logs the call in the hook log (hook "session-end", ms). With the plugin
# option auto_curation it also starts the background curation run (end of this script).
[ -n "${CLAUDE_PLUGIN_OPTION_STORE:-}" ] && export MEM_STORE="$CLAUDE_PLUGIN_OPTION_STORE"
if [ -z "${CLAUDE_PLUGIN_OPTION_STORE:-}" ]; then # no option: the default store, made by session-env.sh
  data="${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}"
  [ -n "$data" ] && [ -f "$data/agent-memory/store/mem-store.yaml" ] && export MEM_STORE="$data/agent-memory/store"
fi
[ -n "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" ] && export MEM_MEMORIES="$CLAUDE_PLUGIN_OPTION_MEMORIES"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || here=""
[ -n "$here" ] && . "$here/find-claude.sh" 2>/dev/null
type find_claude >/dev/null 2>&1 || find_claude() { :; }   # the helper is missing: no claude path, never a failure
# Automatic capture (option auto_capture, exactly "true"): start mem-capture detached with the hook's JSON on its
# standard input, before the commit (which can take seconds and the hook's time may run out; capture writes the
# project, not the store). It checks its own limits, so nothing here waits on a model.
if [ "${CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE:-}" = "true" ] && [ -n "$here" ]; then
  input=$(cat 2>/dev/null)
  claude="$(find_claude)"
  set -- auto --trigger session-end
  [ -n "$claude" ] && set -- "$@" --claude "$claude"
  if command -v setsid >/dev/null 2>&1; then
    (setsid nohup "$here/../bin/mem-capture" "$@" <<<"$input" >/dev/null 2>&1 &) 2>/dev/null
  else
    (nohup "$here/../bin/mem-capture" "$@" <<<"$input" >/dev/null 2>&1 &) 2>/dev/null
  fi
fi
if [ -n "$here" ]; then
  if command -v timeout >/dev/null 2>&1; then
    timeout 5 "$here/../bin/mem" history commit --hook </dev/null >/dev/null 2>&1
  else
    "$here/../bin/mem" history commit --hook </dev/null >/dev/null 2>&1
  fi
fi
# Automatic curation (option auto_curation, exactly "true"): start mem-auto detached, after the commit. It outlives
# this hook (spike, plan 2026-11-17-memory-quiet-synthesis), and checks the lock and the threshold itself, so
# nothing here waits on git or a model.
if [ "${CLAUDE_PLUGIN_OPTION_AUTO_CURATION:-}" = "true" ] && [ -n "$here" ] && [ -n "${MEM_STORE:-}" ]; then
  claude="$(find_claude)"
  set -- run --store "$MEM_STORE"
  [ -n "$claude" ] && set -- "$@" --claude "$claude"
  if command -v setsid >/dev/null 2>&1; then
    (setsid nohup "$here/../bin/mem-auto" "$@" >/dev/null 2>&1 </dev/null &)
  else
    (nohup "$here/../bin/mem-auto" "$@" >/dev/null 2>&1 </dev/null &)
  fi
fi
# Settling what is left (option auto_settle, exactly "true"): the same detached run the write path starts. The run
# asks `mem settle due --minutes 0` itself and exits quietly when nothing waits, so nothing here waits on a model.
if [ "${CLAUDE_PLUGIN_OPTION_AUTO_SETTLE:-}" = "true" ] && [ -n "$here" ] && [ -n "${MEM_STORE:-}" ]; then
  claude="$(find_claude)"
  set -- run --store "$MEM_STORE" --minutes 0
  [ -n "$claude" ] && set -- "$@" --claude "$claude"
  if command -v setsid >/dev/null 2>&1; then
    (setsid nohup "$here/../bin/mem-settle" "$@" >/dev/null 2>&1 </dev/null &)
  else
    (nohup "$here/../bin/mem-settle" "$@" >/dev/null 2>&1 </dev/null &)
  fi
fi
exit 0
