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
if [ -n "$here" ]; then
  if command -v timeout >/dev/null 2>&1; then
    timeout 5 "$here/../bin/mem" history commit --hook </dev/null >/dev/null 2>&1
  else
    "$here/../bin/mem" history commit --hook </dev/null >/dev/null 2>&1
  fi
fi
# Automatic curation (option auto_curation, exactly "true"): start mem-auto detached, after the commit. It outlives
# this hook (spike, plan 2026-11-17-memory-quiet-synthesis), and checks the lock and the threshold itself, so
# nothing here waits on git or a model. The claude binary is the parent process when no variable names it.
if [ "${CLAUDE_PLUGIN_OPTION_AUTO_CURATION:-}" = "true" ] && [ -n "$here" ] && [ -n "${MEM_STORE:-}" ]; then
  claude="${CLAUDE_CODE_EXECPATH:-$(command -v claude 2>/dev/null)}"
  [ -n "$claude" ] || claude="$(readlink "/proc/$PPID/exe" 2>/dev/null)"
  set -- run --store "$MEM_STORE"
  [ -n "$claude" ] && set -- "$@" --claude "$claude"
  if command -v setsid >/dev/null 2>&1; then
    (setsid nohup "$here/../bin/mem-auto" "$@" >/dev/null 2>&1 </dev/null &)
  else
    (nohup "$here/../bin/mem-auto" "$@" >/dev/null 2>&1 </dev/null &)
  fi
fi
exit 0
