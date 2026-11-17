# Sourced by the hooks: find_claude prints the path of the claude binary that runs this session (the running binary
# first, then PATH). Call it in the hook's own shell: it reads the hook's parent process (`$PPID`).
find_claude() {
  local claude="${CLAUDE_CODE_EXECPATH:-}"
  if [ -z "$claude" ]; then
    claude="$(readlink "/proc/$PPID/exe" 2>/dev/null)"
    case "$(basename "${claude:-x}")" in claude|claude.exe) ;; *) claude="$(command -v claude 2>/dev/null)" ;; esac
  fi
  printf '%s' "$claude"
}
