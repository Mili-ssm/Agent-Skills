#!/usr/bin/env bash
# SessionStart hook: prints the memory index that opens the session. The hook's JSON on standard input
# goes to `mem`, which finds the project from its `cwd`. Hook processes do not get the variables that
# session-env.sh exports for shell commands, so the options are passed on here.
# Silent and always exit 0, also when uv or mem fail: a failing hook would disturb every session.
[ -n "${CLAUDE_PLUGIN_OPTION_STORE:-}" ] && export MEM_STORE="$CLAUDE_PLUGIN_OPTION_STORE"
if [ -z "${CLAUDE_PLUGIN_OPTION_STORE:-}" ]; then # no option: the default store, made by session-env.sh
  data="${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}"
  [ -n "$data" ] && [ -f "$data/agent-memory/store/mem-store.yaml" ] && export MEM_STORE="$data/agent-memory/store"
fi
[ -n "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" ] && export MEM_MEMORIES="$CLAUDE_PLUGIN_OPTION_MEMORIES"
[ "${CLAUDE_PLUGIN_OPTION_LOADED_RULES:-}" = "false" ] && export MEM_LOADED_RULES=off   # option loaded_rules, default on
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || here=""
if command -v timeout >/dev/null 2>&1; then input=$(timeout 2 cat 2>/dev/null); else input=$(cat 2>/dev/null); fi   # read once, never wait on an input left open
# Sweep (option auto_capture, exactly "true"): start mem-capture sweep detached, as session-end.sh starts `auto`. It
# captures sessions of this folder that were left open and never ended; nothing here waits on it.
if [ "${CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE:-}" = "true" ] && [ -n "$here" ]; then
  . "$here/find-claude.sh" 2>/dev/null
  type find_claude >/dev/null 2>&1 || find_claude() { :; }   # the helper is missing: no claude path, never a failure
  claude="$(find_claude)"
  set -- sweep
  [ -n "$claude" ] && set -- "$@" --claude "$claude"
  if command -v setsid >/dev/null 2>&1; then
    (setsid nohup "$here/../bin/mem-capture" "$@" <<<"$input" >/dev/null 2>&1 &) 2>/dev/null
  else
    (nohup "$here/../bin/mem-capture" "$@" <<<"$input" >/dev/null 2>&1 &) 2>/dev/null
  fi
fi
out=""
if [ -n "$here" ]; then
  if command -v timeout >/dev/null 2>&1; then
    out="$(timeout 4 "$here/../bin/mem" session-index --hook 2>/dev/null <<<"$input")" || out=""   # bounded, like the first-run init
  else
    out="$("$here/../bin/mem" session-index --hook 2>/dev/null <<<"$input")" || out=""
  fi
fi
if [ -n "$out" ]; then
  printf '%s\n' "$out"
else
  # mem did not answer (no uv, a cold cache, a time-out): the rules still open the session, without the counts.
  cat <<'TXT'
memory: the mem command searches notes and memories (skill: memory).
- Before you act on this project, change something or research a topic: mem search "<topic in English>". It returns decisions, constraints and pitfalls recorded earlier that the files do not show.
- To remember: preferences and personal matters -> auto memory; what a later session would need (a decision, constraint, pitfall or finding) -> mem remember, in English, with --global if it holds in any project and names no business; the project's current situation -> both.
TXT
fi
exit 0
