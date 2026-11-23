#!/usr/bin/env bash
# SessionEnd hook: commits what changed in the store, when the store is a git repository (`mem history init`).
# Options are passed on as in session-index.sh. Silent, always exit 0, and quick: the commit runs detached (below): a failing hook
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
  if command -v timeout >/dev/null 2>&1; then input=$(timeout 2 cat 2>/dev/null); else input=$(cat 2>/dev/null); fi   # never wait on an input left open
  claude="$(find_claude)"
  set -- auto --trigger session-end
  [ -n "$claude" ] && set -- "$@" --claude "$claude"
  if command -v setsid >/dev/null 2>&1; then
    (setsid nohup "$here/../bin/mem-capture" "$@" <<<"$input" >/dev/null 2>&1 &) 2>/dev/null
  else
    (nohup "$here/../bin/mem-capture" "$@" <<<"$input" >/dev/null 2>&1 &) 2>/dev/null
  fi
fi
# The commit and the automatic runs leave the hook: Claude Code gives all SessionEnd hooks one shared 1.5 s budget that
# the hook's `timeout` cannot raise, and the commit runs `mem check` (about 1 s). One detached wrapper keeps the order:
# the commit first (`history commit --hook` skips while an automatic run holds the lock), then mem-auto and mem-settle
# when their options are exactly "true". `--detached` makes mem log a `started` and a `done` record in the hook log, so
# a commit that was killed (30 s) shows as a `started` without its `done`. Each automatic run checks its own lock and
# threshold, so nothing here waits on git or a model.
if [ -n "$here" ]; then
  claude="$(find_claude)"
  auto=0; settle=0
  if [ -n "${MEM_STORE:-}" ]; then
    [ "${CLAUDE_PLUGIN_OPTION_AUTO_CURATION:-}" = "true" ] && auto=1
    [ "${CLAUDE_PLUGIN_OPTION_AUTO_SETTLE:-}" = "true" ] && settle=1
  fi
  wrapper='here=$1; claude=$2; auto=$3; settle=$4
    if command -v timeout >/dev/null 2>&1; then
      timeout 30 "$here/../bin/mem" history commit --hook --detached
    else
      "$here/../bin/mem" history commit --hook --detached
    fi
    if [ "$auto" = 1 ]; then
      set -- run --store "$MEM_STORE"; [ -n "$claude" ] && set -- "$@" --claude "$claude"
      "$here/../bin/mem-auto" "$@" &
    fi
    if [ "$settle" = 1 ]; then
      set -- run --store "$MEM_STORE" --minutes 0; [ -n "$claude" ] && set -- "$@" --claude "$claude"
      "$here/../bin/mem-settle" "$@" &
    fi
    wait'
  if command -v setsid >/dev/null 2>&1; then
    (setsid nohup bash -c "$wrapper" _ "$here" "$claude" "$auto" "$settle" >/dev/null 2>&1 </dev/null &)
  else
    (nohup bash -c "$wrapper" _ "$here" "$claude" "$auto" "$settle" >/dev/null 2>&1 </dev/null &)
  fi
fi
exit 0
