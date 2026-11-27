# Sourced by the hooks when MEM_HOST=codex. Codex sets no CLAUDE_PLUGIN_OPTION_* variables, so codex_options reads each
# plugin option from the file `${XDG_CONFIG_HOME:-$HOME/.config}/agent-memory/<name>` (first line, stripped) and exports
# CLAUDE_PLUGIN_OPTION_<NAME> only when that variable is unset or empty (ADR 0038). `store` and `runner` are left out:
# the engine reads their files itself. A test keeps CODEX_OPTION_NAMES equal to the userConfig keys of plugin.json.
CODEX_OPTION_NAMES="memories auto_curation auto_curation_budget auto_curation_threshold auto_settle auto_settle_minutes auto_capture auto_reword loaded_rules rules_layout auto_capture_budget offload_table research_depth"
codex_options() {
  local base="${XDG_CONFIG_HOME:-${HOME:+$HOME/.config}}" name var line
  [ -n "$base" ] || return 0
  for name in $CODEX_OPTION_NAMES; do
    var="CLAUDE_PLUGIN_OPTION_$(printf '%s' "$name" | tr '[:lower:]' '[:upper:]')"
    [ -n "${!var:-}" ] && continue
    line=""
    [ -r "$base/agent-memory/$name" ] && { IFS= read -r line < "$base/agent-memory/$name"; } 2>/dev/null
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -n "$line" ] && export "$var=$line"
  done
  return 0
}
