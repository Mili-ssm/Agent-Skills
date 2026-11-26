# Sourced by the hooks: the one place that says which note store a hook uses.
# default_store_dir prints the default store folder when it holds `mem-store.yaml` (the marker, not the folder:
# an init cut short leaves a folder without it), else nothing.
# config_store prints the first line of the `store` config file (stripped), else nothing.
# export_store_env exports MEM_STORE (option `store`, else the default store unless the config file names a store:
# then `mem` resolves it) and MEM_MEMORIES (option `memories`).
default_store_dir() {
  local data="${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}"
  [ -n "$data" ] && [ -f "$data/agent-memory/store/mem-store.yaml" ] && printf '%s' "$data/agent-memory/store"
  return 0
}
config_store() {
  local line="" file="${XDG_CONFIG_HOME:-$HOME/.config}/agent-memory/store"
  [ -r "$file" ] && { IFS= read -r line < "$file"; } 2>/dev/null
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  printf '%s' "$line"
  return 0
}
export_store_env() {
  local dir
  if [ -n "${CLAUDE_PLUGIN_OPTION_STORE:-}" ]; then
    export MEM_STORE="$CLAUDE_PLUGIN_OPTION_STORE"
  else
    if [ -z "$(config_store)" ]; then
      dir="$(default_store_dir)"
      [ -n "$dir" ] && export MEM_STORE="$dir"
    fi
  fi
  [ -n "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" ] && export MEM_MEMORIES="$CLAUDE_PLUGIN_OPTION_MEMORIES"
  return 0
}
