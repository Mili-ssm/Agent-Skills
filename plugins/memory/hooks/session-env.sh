#!/usr/bin/env bash
# SessionStart hook: hands the plugin's `store` and `memories` options to the session's shell
# commands (they do not receive plugin options) and to the config files `mem` falls back on.
# With no `store` option it makes the default store on the first run and hands that one over.
# A config file the hook did not write (no matching `<name>.hook` record) is never overwritten or removed.
# Silent and always exit 0: a failing hook would disturb every session.
cfg="${XDG_CONFIG_HOME:-$HOME/.config}/agent-memory"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || here=""
. "$here/store-env.sh" 2>/dev/null
store_helper=1
type default_store_dir >/dev/null 2>&1 || { store_helper=""; default_store_dir() { :; }; }   # helper missing: no default store, never a failure
type config_store >/dev/null 2>&1 || config_store() { :; }
export_var() { # <variable> <value>
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    { printf 'export %s=%q\n' "$1" "$2" >> "$CLAUDE_ENV_FILE"; } 2>/dev/null
  fi
  return 0
}
handle() { # <option value> <config file name> <variable>
  # `$cfg/<name>.hook` records what this hook wrote: a file with other content was written or edited by hand and stays.
  local file="$cfg/$2" record="$cfg/$2.hook" current="" recorded=""
  [ -f "$file" ] && current="$(cat "$file" 2>/dev/null; printf x)"
  [ -f "$record" ] && recorded="$(cat "$record" 2>/dev/null; printf x)"
  if [ -z "$1" ]; then
    # The option was cleared: remove the file only when this hook wrote it.
    [ -n "$current" ] && [ "$current" = "$recorded" ] && rm -f "$file" 2>/dev/null
    rm -f "$record" 2>/dev/null
    return 0
  fi
  if [ -z "$current" ] || [ "$current" = "$recorded" ]; then
    { mkdir -p "$cfg" && printf '%s\n' "$1" > "$file" && printf '%s\n' "$1" > "$record"; } >/dev/null 2>&1
  fi
  export_var "$3" "$1"
}
default_store() {
  [ -n "$store_helper" ] || return 0
  [ -n "${XDG_DATA_HOME:-${HOME:-}}" ] || return 0   # no data folder: `mem init` could only fail
  # The marker, not the folder: an init cut short by the time limit is finished on the next start.
  if [ -z "$(default_store_dir)" ] && [ -n "$here" ]; then
    if command -v timeout >/dev/null 2>&1; then
      timeout 4 "$here/../bin/mem" init >/dev/null 2>&1 || true   # bounded: a cold cache without network must not hold the session
    else
      "$here/../bin/mem" init >/dev/null 2>&1 || true
    fi
  fi
  local dir
  dir="$(default_store_dir)"
  [ -n "$dir" ] && export_var MEM_STORE "$dir"
  return 0
}
if [ -n "${CLAUDE_PLUGIN_OPTION_STORE:-}" ]; then
  handle "$CLAUDE_PLUGIN_OPTION_STORE" store MEM_STORE
else
  handle "" store MEM_STORE
  # A `store` config file that names a store is `mem`'s to resolve: no default store is exported over it.
  named="$(config_store)"
  if [ -n "$named" ]; then export_var MEM_STORE "$named"; else default_store; fi
fi
handle "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" memories MEM_MEMORIES
# The runner option for shell commands (the write path starts settle from them). It is MEM_RUNNER_OPTION, never
# MEM_RUNNER: the `runner` config file and `--runner` must outrank it. Hooks pass it to the passes they start.
[ -n "${CLAUDE_PLUGIN_OPTION_RUNNER:-}" ] && export_var MEM_RUNNER_OPTION "$CLAUDE_PLUGIN_OPTION_RUNNER"
# mem-research, run from a shell command of this session, needs the claude binary and the owner's default depth; the
# hook's CLAUDE_PLUGIN_OPTION_* variables do not reach shell commands.
[ -n "$here" ] && . "$here/find-claude.sh" 2>/dev/null
if type find_claude >/dev/null 2>&1; then
  research_claude="$(find_claude)"
  [ -n "$research_claude" ] && export_var MEM_CLAUDE "$research_claude"
fi
case "${CLAUDE_PLUGIN_OPTION_RESEARCH_DEPTH:-}" in
  memory|contrast|deep) export_var MEM_RESEARCH_DEPTH "$CLAUDE_PLUGIN_OPTION_RESEARCH_DEPTH" ;;
esac
# The loaded rules layout, so `mem rules` typed in a session prints what the session start printed.
case "${CLAUDE_PLUGIN_OPTION_RULES_LAYOUT:-}" in grouped|digest) export_var MEM_RULES_LAYOUT "$CLAUDE_PLUGIN_OPTION_RULES_LAYOUT" ;; esac
# Background settling (option auto_settle, exactly "true"): the variables below are what lets the write path of this
# session's shell commands start a settling run; no variable, no trigger (a trial or a test never has them).
if [ "${CLAUDE_PLUGIN_OPTION_AUTO_SETTLE:-}" = "true" ]; then
  [ -n "$here" ] && . "$here/find-claude.sh" 2>/dev/null
  claude=""
  type find_claude >/dev/null 2>&1 && claude="$(find_claude)"
  export_var MEM_SETTLE_AUTO 1
  export_var MEM_SETTLE_MINUTES "${CLAUDE_PLUGIN_OPTION_AUTO_SETTLE_MINUTES:-30}"
  [ -n "$claude" ] && export_var MEM_SETTLE_CLAUDE "$claude"
  # `settle log` creates the settle state when it is missing and records the memories that exist as judged, so the
  # first write after the option is turned on is not taken as already judged.
  store="${CLAUDE_PLUGIN_OPTION_STORE:-}"
  [ -n "$store" ] || store="$(config_store)"
  [ -n "$store" ] || store="$(default_store_dir)"
  if [ -n "$here" ] && [ -n "$store" ]; then
    if command -v timeout >/dev/null 2>&1; then
      MEM_STORE="$store" MEM_MEMORIES="${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" timeout 3 "$here/../bin/mem" settle log </dev/null >/dev/null 2>&1
    else
      MEM_STORE="$store" MEM_MEMORIES="${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" "$here/../bin/mem" settle log </dev/null >/dev/null 2>&1
    fi
  fi
fi
exit 0
