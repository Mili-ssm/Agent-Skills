# Sourced by the hooks: the one place that says which note store a hook uses.
# default_store_dir prints the default store folder when it holds `mem-store.yaml` (the marker, not the folder:
# an init cut short leaves a folder without it), else nothing.
# config_store prints the first line of the `store` config file (stripped), else nothing.
# export_store_env exports MEM_STORE (option `store`, else the store the config file names, else the default store,
# the precedence of engine/core/config.py) and MEM_MEMORIES (option `memories`).
default_store_dir() {
  local data="${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}"
  [ -n "$data" ] && [ -f "$data/agent-memory/store/mem-store.yaml" ] && printf '%s' "$data/agent-memory/store"
  return 0
}
config_store() {
  local line="" base="${XDG_CONFIG_HOME:-${HOME:+$HOME/.config}}"
  [ -n "$base" ] || return 0   # no HOME and no XDG_CONFIG_HOME: no config file, as in engine/core/config.py
  [ -r "$base/agent-memory/store" ] && { IFS= read -r line < "$base/agent-memory/store"; } 2>/dev/null
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
    dir="$(config_store)"
    [ -n "$dir" ] || dir="$(default_store_dir)"
    [ -n "$dir" ] && export MEM_STORE="$dir"
  fi
  [ -n "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" ] && export MEM_MEMORIES="$CLAUDE_PLUGIN_OPTION_MEMORIES"
  return 0
}
